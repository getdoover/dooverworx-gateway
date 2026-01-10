import asyncio
import os
import time
from pathlib import Path

from pydoover.docker import Application

from .app_config import DooverworxGatewayConfig

class DooverworxGatewayApplication(Application):
    config: DooverworxGatewayConfig  # not necessary, but helps your IDE provide autocomplete!

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started: float = time.time()

        self.loop_target_period = None

    async def setup(self):
        """Start the entrypoint.sh script with configuration."""
        script_path = Path(__file__).parent / "entrypoint.sh"
        # script_path.chmod(0o755)
        
        env = os.environ.copy()
        env["TARGET_IFACE"] = self.config.target_interface.value
        env["OPENVPN_PORT"] = str(self.config.openvpn_port.value)
        
        await asyncio.create_subprocess_exec(
            str(script_path),
            env=env,
        )

    async def main_loop(self):
        pass