"""
Base cache layer for persistence management.
Supports CSV-based caching for MVP.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional
import csv
from datetime import datetime


class BaseCacheLayer(ABC):
    """Abstract base class for cache persistence."""
    
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    @abstractmethod
    def read(self, cache_name: str) -> List[Dict[str, Any]]:
        """Read cache from storage."""
        pass
    
    @abstractmethod
    def write(self, cache_name: str, data: List[Dict[str, Any]]) -> bool:
        """Write cache to storage."""
        pass
    
    @abstractmethod
    def append(self, cache_name: str, record: Dict[str, Any]) -> bool:
        """Append single record to cache."""
        pass
    
    @abstractmethod
    def delete(self, cache_name: str) -> bool:
        """Delete cache file."""
        pass


class CSVCacheLayer(BaseCacheLayer):
    """CSV-based cache persistence for MVP."""
    
    def __init__(self, cache_dir: str = "cache"):
        super().__init__(cache_dir)
    
    def _get_path(self, cache_name: str) -> Path:
        """Get full path for cache file."""
        return self.cache_dir / f"{cache_name}.csv"
    
    def read(self, cache_name: str) -> List[Dict[str, Any]]:
        """Read CSV cache file."""
        path = self._get_path(cache_name)
        if not path.exists():
            return []
        
        data = []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                data = list(reader) if reader else []
        except Exception as e:
            print(f"Error reading {cache_name}: {e}")
        
        return data
    
    def write(self, cache_name: str, data: List[Dict[str, Any]]) -> bool:
        """Write data to CSV cache file."""
        if not data:
            return False
        
        path = self._get_path(cache_name)
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                fieldnames = data[0].keys()
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)
            return True
        except Exception as e:
            print(f"Error writing {cache_name}: {e}")
            return False
    
    def append(self, cache_name: str, record: Dict[str, Any]) -> bool:
        """Append single record to CSV cache."""
        path = self._get_path(cache_name)
        try:
            # Check if file exists and has content
            file_exists = path.exists() and path.stat().st_size > 0
            
            with open(path, 'a', newline='', encoding='utf-8') as f:
                fieldnames = record.keys()
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                
                # Write header if file is new
                if not file_exists:
                    writer.writeheader()
                
                writer.writerow(record)
            return True
        except Exception as e:
            print(f"Error appending to {cache_name}: {e}")
            return False
    
    def delete(self, cache_name: str) -> bool:
        """Delete cache file."""
        path = self._get_path(cache_name)
        try:
            if path.exists():
                path.unlink()
            return True
        except Exception as e:
            print(f"Error deleting {cache_name}: {e}")
            return False
