from pydoover.docker import run_app

from .application import DooverworxGatewayApplication
from .app_config import DooverworxGatewayConfig

def main():
    """
    Run the application.
    """
    run_app(DooverworxGatewayApplication(config=DooverworxGatewayConfig()))
