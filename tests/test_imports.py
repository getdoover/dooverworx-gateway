"""
Basic tests for an application.

This ensures all modules are importable and that the config is valid.
"""

def test_import_app():
    from dooverworx_gateway.application import DooverworxGatewayApplication
    assert DooverworxGatewayApplication

def test_config():
    from dooverworx_gateway.app_config import DooverworxGatewayConfig

    config = DooverworxGatewayConfig()
    assert isinstance(config.to_dict(), dict)

def test_ui():
    from dooverworx_gateway.app_ui import DooverworxGatewayUI
    assert DooverworxGatewayUI

def test_state():
    from dooverworx_gateway.app_state import DooverworxGatewayState
    assert DooverworxGatewayState