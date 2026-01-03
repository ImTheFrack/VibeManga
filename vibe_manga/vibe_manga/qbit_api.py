import os
import requests
import logging
from typing import Optional, List, Dict, Any
from .logging import get_logger, log_api_call

logger = get_logger(__name__)

class QBitAPI:
    def __init__(self):
        self.base_url = os.getenv("QBIT_URL", "http://localhost:8080").rstrip("/")
        self.username = os.getenv("QBIT_USER", "admin")
        self.password = os.getenv("QBIT_PASS", "adminadmin")
        self.session = requests.Session()
        self.sid = None

    def login(self) -> bool:
        """Log in to qBittorrent and retrieve SID."""
        login_url = f"{self.base_url}/api/v2/auth/login"
        headers = {"Referer": self.base_url}
        data = {
            "username": self.username,
            "password": self.password
        }
        log_api_call(login_url, "POST", params=data)
        try:
            response = self.session.post(login_url, headers=headers, data=data)
            if response.status_code == 200 and "SID" in self.session.cookies:
                self.sid = self.session.cookies["SID"]
                logger.info("Successfully logged in to qBittorrent")
                return True
            else:
                logger.error(f"Failed to login to qBittorrent: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error connecting to qBittorrent: {e}")
            return False

    def add_torrent(self, urls: List[str], tag: str = "VibeManga", savepath: str = "VibeManga") -> bool:
        """Add one or more torrents via URLs/magnets."""
        if not self.sid and not self.login():
            return False

        add_url = f"{self.base_url}/api/v2/torrents/add"
        
        # multipart/form-data
        files = {
            "urls": (None, "\n".join(urls)),
            "tags": (None, tag),
            "savepath": (None, savepath)
        }
        log_api_call(add_url, "POST", params={"count": len(urls), "tag": tag})

        try:
            response = self.session.post(add_url, files=files)
            if response.status_code == 200:
                logger.info(f"Successfully added {len(urls)} torrents to qBittorrent")
                return True
            else:
                logger.error(f"Failed to add torrents: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error adding torrents: {e}")
            return False

    def get_torrents_info(self, tag: Optional[str] = "VibeManga") -> List[Dict[str, Any]]:
        """Retrieve information about torrents, optionally filtered by tag."""
        if not self.sid and not self.login():
            return []

        info_url = f"{self.base_url}/api/v2/torrents/info"
        params = {}
        if tag:
            params["tag"] = tag
        log_api_call(info_url, "GET", params=params)

        try:
            response = self.session.get(info_url, params=params)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get torrents info: {response.status_code} {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error getting torrents info: {e}")
            return []

    def pause_torrents(self, hashes: List[str]) -> bool:
        """Pause (stop) one or more torrents. Supports both old 'pause' and new 'stop' endpoints."""
        if not self.sid and not self.login():
            return False

        # Try 'stop' first (qBit 4.6.0+)
        stop_url = f"{self.base_url}/api/v2/torrents/stop"
        data = {"hashes": "|".join(hashes)}
        log_api_call(stop_url, "POST", params={"count": len(hashes)})

        try:
            response = self.session.post(stop_url, data=data)
            if response.status_code == 200:
                logger.info(f"Successfully stopped {len(hashes)} torrents")
                return True
            
            # If 404, try the older 'pause' endpoint
            if response.status_code == 404:
                pause_url = f"{self.base_url}/api/v2/torrents/pause"
                response = self.session.post(pause_url, data=data)
                if response.status_code == 200:
                    logger.info(f"Successfully paused {len(hashes)} torrents")
                    return True

            logger.error(f"Failed to stop/pause torrents: {response.status_code} {response.text}")
            return False
        except Exception as e:
            logger.error(f"Error pausing torrents: {e}")
            return False

    def delete_torrents(self, hashes: List[str], delete_files: bool = True) -> bool:
        """Delete one or more torrents, optionally deleting their downloaded data."""
        if not self.sid and not self.login():
            return False

        delete_url = f"{self.base_url}/api/v2/torrents/delete"
        data = {
            "hashes": "|".join(hashes),
            "deleteFiles": "true" if delete_files else "false"
        }
        log_api_call(delete_url, "POST", params={"count": len(hashes), "delete_files": delete_files})

        try:
            response = self.session.post(delete_url, data=data)
            if response.status_code == 200:
                logger.info(f"Successfully deleted {len(hashes)} torrents (delete_files={delete_files})")
                return True
            else:
                logger.error(f"Failed to delete torrents: {response.status_code} {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error deleting torrents: {e}")
            return False
