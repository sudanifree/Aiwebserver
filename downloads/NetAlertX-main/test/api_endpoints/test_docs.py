# test/api_endpoints/test_docs.py - Tests for root redirect and API docs endpoints


from api_server import api_server_start


def test_index_redirect_logic():
    """Test the redirect function logic directly."""
    with api_server_start.app.test_client() as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert response.location == '/docs'


def test_api_docs_logic():
    """Test that api_docs attempts to serve the correct file."""
    with api_server_start.app.test_client() as client:
        response = client.get("/docs")
        assert response.status_code == 200
        assert response.mimetype == "text/html"
        response.direct_passthrough = False
        data = response.get_data()
        assert b"<!DOCTYPE html>" in data or b"<html>" in data
