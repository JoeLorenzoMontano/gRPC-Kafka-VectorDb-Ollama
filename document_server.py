import grpc
import os
import uuid
import json
from concurrent import futures
from confluent_kafka import Producer
import document_pb2
import document_pb2_grpc
from config import kafka_config, storage_config, grpc_config

# Kafka Producer
producer = Producer({"bootstrap.servers": kafka_config.bootstrap_servers})

class DocumentService(document_pb2_grpc.DocumentServiceServicer):
    def UploadDocument(self, request, context):
        document_id = str(uuid.uuid4())
        filepath = os.path.join(storage_config.storage_dir, document_id)

        try:
            with open(filepath, "wb") as f:
                f.write(request.content)

            # Send Kafka event
            event = json.dumps({
                "document_id": document_id,
                "filename": request.filename,
                "content_type": "pdf" if request.filename.endswith(".pdf") else "text"
            })
            producer.produce(kafka_config.document_topic, key=document_id, value=event)
            producer.flush()

            return document_pb2.UploadResponse(
                document_id=document_id,
                message=f"Document '{request.filename}' uploaded successfully!"
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error storing document: {str(e)}")
            return document_pb2.UploadResponse(document_id="", message="Failed to upload document.")

    def GetDocument(self, request, context):
        filepath = os.path.join(storage_config.storage_dir, request.document_id)

        if not os.path.exists(filepath):
            context.set_code(grpc.StatusCode.NOT_FOUND)
            return document_pb2.DocumentResponse()

        try:
            with open(filepath, "rb") as f:
                content = f.read()

            return document_pb2.DocumentResponse(
                filename=request.document_id,
                content=content
            )
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            return document_pb2.DocumentResponse()

    def DownloadDocument(self, request, context):
        """Streams document content in chunks to the client"""
        filepath = os.path.join(storage_config.storage_dir, request.document_id)

        if not os.path.exists(filepath):
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Document not found")
            return

        try:
            with open(filepath, "rb") as f:
                while chunk := f.read(grpc_config.chunk_size):  # Stream in chunks
                    yield document_pb2.DocumentChunk(file_data=chunk)
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error reading document: {str(e)}")

def serve():
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=grpc_config.max_workers),
        options=[
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),  # 100MB
            ("grpc.max_send_message_length", 100 * 1024 * 1024)  # 100MB
        ]
    )
    document_pb2_grpc.add_DocumentServiceServicer_to_server(DocumentService(), server)
    server_address = f"{grpc_config.server_host}:{grpc_config.server_port}"
    server.add_insecure_port(server_address)
    print(f"Document gRPC server is running on {server_address}...")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
