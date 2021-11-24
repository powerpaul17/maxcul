import pytest
from typing import Dict

import custom_components.maxcul
from custom_components.maxcul import (
    MaxCulConnection
)

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    pass

@pytest.fixture(autouse=True)
def max_connection_factory(monkeypatch: pytest.MonkeyPatch):
    factory = MockConnectionFactory()
    mock_connection_create_function = factory.get_create_function()
    monkeypatch.setattr(custom_components.maxcul, 'MaxCulConnection', mock_connection_create_function)
    return factory

class MockConnectionFactory():

    def __init__(self):
        self.connections: Dict[str, MockConnection] = {}

    def get_create_function(self):
        def create_function(hass, device_path, sender_id):
            return self.create(hass, device_path, sender_id)

        return create_function

    def create(self, hass, device_path, sender_id):
        connection = MockConnection(hass, device_path, sender_id)
        self.connections[device_path] = connection
        return connection

class MockConnection(MaxCulConnection):

    def __init__(
        self,
        hass,
        device_path,
        sender_id
    ):
        super().__init__(hass, device_path, sender_id)

    def start(self):
        pass

    def enable_pairing(self, duration):
        pass

    def add_paired_device(self, device_id):
        pass

    def call_callback(self, event, payload):
        self._callback(event, payload)
