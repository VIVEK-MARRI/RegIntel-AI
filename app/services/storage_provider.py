import os
import shutil
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

class StorageProvider(ABC):
    """Abstract Base Class defining the file storage contract."""
    
    @abstractmethod
    async def save_file(self, file_data: BinaryIO, destination: str) -> None:
        """Saves file binary data to the destination path/URI."""
        pass

    @abstractmethod
    async def delete_file(self, destination: str) -> None:
        """Deletes the file at the destination path/URI."""
        pass

    @abstractmethod
    async def file_exists(self, destination: str) -> bool:
        """Checks if a file exists at the destination path/URI."""
        pass

class LocalStorageProvider(StorageProvider):
    """Local filesystem storage implementation."""
    
    def __init__(self, root_dir: str):
        self.root_path = Path(root_dir).resolve()
        logger.info(f"Initialized LocalStorageProvider with root: {self.root_path}")

    async def save_file(self, file_data: BinaryIO, destination: str) -> None:
        """Saves binary file data locally on disk, creating directories as needed."""
        dest_path = (self.root_path / destination).resolve()
        
        # Security check to prevent path traversal
        if not dest_path.is_relative_to(self.root_path):
            logger.error(f"Path traversal attempt blocked: {destination}")
            raise ValueError("Path traversal attempt detected")
            
        # Create directories if they do not exist
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file data
        logger.debug(f"Saving file locally to {dest_path}")
        try:
            with open(dest_path, "wb") as f:
                # Seek to start of file to ensure we read from the beginning
                file_data.seek(0)
                shutil.copyfileobj(file_data, f)
        except Exception as e:
            logger.error(f"Failed to save file locally to {dest_path}: {e}")
            raise IOError(f"Could not write file to disk: {e}") from e

    async def delete_file(self, destination: str) -> None:
        """Deletes the file locally from disk."""
        dest_path = (self.root_path / destination).resolve()
        
        # Security check to prevent path traversal
        if not dest_path.is_relative_to(self.root_path):
            logger.error(f"Path traversal attempt blocked during delete: {destination}")
            raise ValueError("Path traversal attempt detected")
            
        if dest_path.exists() and dest_path.is_file():
            logger.debug(f"Deleting file locally from {dest_path}")
            try:
                dest_path.unlink()
            except Exception as e:
                logger.error(f"Failed to delete file from {dest_path}: {e}")
                raise IOError(f"Could not delete file from disk: {e}") from e
        else:
            logger.warning(f"Attempted to delete non-existent file: {dest_path}")

    async def file_exists(self, destination: str) -> bool:
        """Checks if a file exists locally on disk."""
        dest_path = (self.root_path / destination).resolve()
        
        # Security check to prevent path traversal
        if not dest_path.is_relative_to(self.root_path):
            logger.error(f"Path traversal attempt blocked during exists check: {destination}")
            raise ValueError("Path traversal attempt detected")
            
        return dest_path.exists() and dest_path.is_file()
