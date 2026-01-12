import os, pytest

@pytest.fixture(scope="session", autouse=True)
def _set_test_env():
    # Use a throwaway SQLite database for app init (app should still require DATABASE_URL)
    os.environ.setdefault('DATABASE_URL', 'sqlite:///./test.db')
    os.environ.setdefault('AUTH_DEV_ISSUE_TOKENS', '1')
    os.environ.setdefault('ALLOWED_ORIGINS', 'http://localhost:3000')
    return True

@pytest.fixture()
def client():
    # Minimal import & app client
    from backend.api import app
    with app.test_client() as c:
        yield c

class ClientHelpers:
    def __init__(self, c):
        self.c = c

    def post_json(self, url, payload, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return self.c.post(url, json=payload, headers=headers)

    def get_json(self, url, token=None):
        headers = {}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return self.c.get(url, headers=headers)

@pytest.fixture()
def helper(client):
    return ClientHelpers(client)

