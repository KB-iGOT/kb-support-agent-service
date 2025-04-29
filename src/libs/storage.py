"""
Storage utility for uploading files to GCP bucket
making it available for audio conversions
"""
import os
from typing import Union, Optional
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from google.cloud import storage
from google.oauth2 import service_account

load_dotenv()

class Storage(ABC):
    """
    Abstract class for storage operations
    """
    @abstractmethod
    def write_file(
        self,
        file_path: str,
        file_content: Union[str, bytes],
        mime_type: Optional[str] = None,
    ):
        """
        Write file to internal storage
        """

    @abstractmethod
    def public_url(self, file_path: str) -> str:
        """
        Get public URL of the file
        """
        # pass

class GCPStorage(Storage):
    """
    GCP Storage class for uploading files to GCP bucket
    """
    __client__ = None

    def __init__(self):
        bucket_name = os.getenv("GCP_BUCKET_NAME")
        storage_credentials_json = os.getenv("GCP_STORAGE_CREDENTIALS")
        credentials = service_account.Credentials.from_service_account_file(
            storage_credentials_json)
        if not bucket_name or not storage_credentials_json:
            raise ValueError(
                "GCPStorage client not initialized. Missing google bucket_name or crendentials")
        self.__bucket_name__ = bucket_name
        self.__client__ = storage.Client(credentials=credentials)


    def write_file(
        self,
        file_path: str,
        file_content: Union[str, bytes],
        mime_type: Optional[str] = None,
    ):
        if not self.__client__:
            raise Exception("GCPSyncStorage client not initialized")

        bucket = self.__client__.bucket(self.__bucket_name__)
        blob = bucket.blob(file_path)

        if mime_type is None:
            mime_type = (
                    "audio/mpeg" 
                    if file_path.lower().endswith('.mp3')
                    else "audio/mpeg")

        blob.upload_from_string(file_content, content_type=mime_type)
        print(f"File uploaded to GCP bucket: {file_path}")

    def public_url(self, file_path: str) -> str:
        if not self.__client__:
            raise Exception("GCP Storage client not initialized")

        bucket = self.__client__.bucket(self.__bucket_name__)
        blob = bucket.blob(file_path)
        blob.make_public()
        print(f"GCP Public URL :: {blob.public_url}")
        return blob.public_url
