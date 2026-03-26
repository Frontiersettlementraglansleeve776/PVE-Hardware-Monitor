"""Cluster monitoring for multi-node Proxmox VE clusters."""
import asyncio
import json
import time
from dataclasses import asdict
from typing import Optional, Callable, TYPE_CHECKING
import aiohttp

if TYPE_CHECKING:
    from .config import ClusterConfig, NodeConfig
    from .types import NodeInfo


try:
    from .config import ClusterConfig, NodeConfig, NodeInfo
except ImportError:
    from pvehw.config import ClusterConfig, NodeConfig
    from pvehw.types import NodeInfo


class ClusterMonitor:
    """Monitor multiple Proxmox nodes in a cluster."""
    
    def __init__(self, config: ClusterConfig, 
                 on_node_update: Optional[Callable[[str, dict], None]] = None):
        self._config = config
        self._nodes: dict[str, NodeInfo] = {}
        self._on_update = on_node_update
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    def add_node(self, node: NodeConfig) -> None:
        """Add a node to the cluster."""
        self._nodes[node.name] = NodeInfo(
            name=node.name,
            host=node.host,
            port=node.port,
            token=node.token,
            enabled=node.enabled
        )
    
    def remove_node(self, name: str) -> None:
        """Remove a node from the cluster."""
        if name in self._nodes:
            del self._nodes[name]
    
    async def _fetch_node_status(self, node: NodeInfo) -> dict:
        """Fetch status from a single node."""
        headers = {}
        if node.token:
            headers["X-Api-Token"] = node.token
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"http://{node.host}:{node.port}/api/status"
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return {"ok": False, "error": f"HTTP {resp.status}"}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    async def _poll_loop(self) -> None:
        """Main polling loop for cluster nodes."""
        while self._running:
            tasks = []
            for name, node in self._nodes.items():
                if node.enabled:
                    tasks.append(self._poll_node(name))
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            
            await asyncio.sleep(self._config.poll_interval)
    
    async def _poll_node(self, name: str) -> None:
        """Poll a single node and update its status."""
        node = self._nodes.get(name)
        if not node:
            return
        
        status = await self._fetch_node_status(node)
        node.status = status
        
        if self._on_update:
            self._on_update(name, status)
    
    async def poll_all(self) -> dict[str, Optional[dict]]:
        """Poll all nodes and return their status."""
        tasks = {name: self._poll_node(name) for name, node in self._nodes.items() if node.enabled}
        if tasks:
            await asyncio.gather(*tasks.values(), return_exceptions=True)
        return {name: node.status for name, node in self._nodes.items()}
    
    def get_node(self, name: str) -> Optional[NodeInfo]:
        """Get node info by name."""
        return self._nodes.get(name)
    
    def get_all_nodes(self) -> list[NodeInfo]:
        """Get all nodes."""
        return list(self._nodes.values())
    
    def get_all_status(self) -> dict[str, Optional[dict]]:
        """Get status of all nodes."""
        return {name: node.status for name, node in self._nodes.items()}
    
    async def start(self) -> None:
        """Start the cluster monitoring loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
    
    async def stop(self) -> None:
        """Stop the cluster monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


class TLSManager:
    """Manage TLS certificates for HTTPS."""
    
    @staticmethod
    def generate_self_signed(cert_path: str, key_path: str, 
                            common_name: str = "localhost",
                            days_valid: int = 365) -> bool:
        """Generate a self-signed certificate."""
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            import datetime
            
            key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PVE Hardware Monitor"),
            ])
            
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.utcnow())
                .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=days_valid))
                .sign(key, hashes.SHA256(), default_backend())
            )
            
            with open(cert_path, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
            
            with open(key_path, "wb") as f:
                f.write(key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            
            return True
        except ImportError:
            return TLSManager._generate_openssl(cert_path, key_path, common_name)
        except Exception:
            return False
    
    @staticmethod
    def _generate_openssl(cert_path: str, key_path: str, common_name: str) -> bool:
        """Generate self-signed cert using OpenSSL CLI."""
        import subprocess
        try:
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", key_path, "-out", cert_path,
                "-days", "365", "-nodes",
                "-subj", f"/CN={common_name}/O=PVE Hardware Monitor"
            ], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    @staticmethod
    def create_ssl_context(cert_path: str, key_path: str) -> Optional[object]:
        """Create an SSL context for the server."""
        import ssl
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert_path, key_path)
            return ctx
        except (ssl.SSLError, FileNotFoundError):
            return None
