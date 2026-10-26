"""HA-Tests der Integration. Aufruf (venv mit homeassistant + pytest-homeassistant-custom-component): pytest tests_ha"""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Recorder vor hass einrichten (Integration hängt vom Recorder ab), Custom Integrations erlauben."""
    yield
