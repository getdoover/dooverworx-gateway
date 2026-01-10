from pathlib import Path

from pydoover import config


class DooverworxGatewayConfig(config.Schema):
    def __init__(self):

        self.target_interface = config.String("Target Interface", default="eth0", description="The interface to attach to. Can be a bridge or a normal interface. e.g. br0 or eth0.")
        self.openvpn_port = config.Integer("OpenVPN Port", default=1194, description="The port the server will listen on.")
        # self.bridge_name = config.String("Bridge Name", default="dv_vpn_bridge")
        # self.tap_name = config.String("Tap Name", default="tap0")
        # self.mtu = config.Integer("MTU", default=1300)


def export():
    DooverworxGatewayConfig().export(Path(__file__).parents[2] / "doover_config.json", "dooverworx_gateway")

if __name__ == "__main__":
    export()
