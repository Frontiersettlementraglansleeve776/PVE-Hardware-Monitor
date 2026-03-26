"""WebSocket manager for real-time updates."""
import asyncio
import json
from typing import Callable, Set
import threading


class WebSocketManager:
    """Manages WebSocket connections for real-time status updates."""
    
    def __init__(self):
        self._connections: Set[Callable] = set()
        self._lock = threading.Lock()
    
    def register(self, handler: Callable) -> None:
        """Register a WebSocket connection."""
        with self._lock:
            self._connections.add(handler)
    
    def unregister(self, handler: Callable) -> None:
        """Unregister a WebSocket connection."""
        with self._lock:
            self._connections.discard(handler)
    
    async def broadcast(self, message: str) -> None:
        """Broadcast message to all connected clients."""
        with self._lock:
            connections = list(self._connections)
        
        for conn in connections:
            try:
                await conn(message)
            except Exception:
                with self._lock:
                    self._connections.discard(conn)
    
    def count(self) -> int:
        """Get number of active connections."""
        with self._lock:
            return len(self._connections)


class WebSocketFrame:
    """WebSocket frame parsing and building utilities."""
    
    @staticmethod
    def parse_frame(data: bytes) -> tuple[bool, bool, bytes]:
        """Parse WebSocket frame. Returns (final, masked, payload)."""
        if len(data) < 2:
            return False, False, b""
        
        first = data[0]
        final = (first & 0x80) != 0
        opcode = first & 0x0F
        
        second = data[1]
        masked = (second & 0x80) != 0
        length = second & 0x7F
        
        offset = 2
        if length == 126:
            if len(data) < 4:
                return False, masked, b""
            length = int.from_bytes(data[2:4], "big")
            offset = 4
        elif length == 127:
            if len(data) < 10:
                return False, masked, b""
            length = int.from_bytes(data[2:10], "big")
            offset = 10
        
        if len(data) < offset + length:
            return False, masked, b""
        
        payload = data[offset:offset + length]
        if masked:
            mask = data[offset - 4:offset]
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        
        return final, masked, payload
    
    @staticmethod
    def build_frame(payload: bytes, opcode: int = 1) -> bytes:
        """Build WebSocket frame."""
        length = len(payload)
        frame = bytearray()
        frame.append(0x80 | opcode)
        
        if length < 126:
            frame.append(length)
        elif length < 65536:
            frame.append(126)
            frame.extend(length.to_bytes(2, "big"))
        else:
            frame.append(127)
            frame.extend(length.to_bytes(8, "big"))
        
        frame.extend(payload)
        return bytes(frame)
    
    @staticmethod
    def build_text_frame(message: str) -> bytes:
        """Build WebSocket text frame."""
        return WebSocketFrame.build_frame(message.encode("utf-8"), opcode=1)
    
    @staticmethod
    def build_ping_frame() -> bytes:
        """Build WebSocket ping frame."""
        return WebSocketFrame.build_frame(b"", opcode=9)
    
    @staticmethod
    def build_pong_frame() -> bytes:
        """Build WebSocket pong frame."""
        return WebSocketFrame.build_frame(b"", opcode=10)
    
    @staticmethod
    def build_close_frame(code: int = 1000, reason: str = "") -> bytes:
        """Build WebSocket close frame."""
        payload = code.to_bytes(2, "big") + reason.encode("utf-8")
        return WebSocketFrame.build_frame(payload, opcode=8)
