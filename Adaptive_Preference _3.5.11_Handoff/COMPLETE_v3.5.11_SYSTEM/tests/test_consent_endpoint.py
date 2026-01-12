def test_consent_endpoint(helper):
    r = helper.get_json('/api/consent')
    assert r.status_code in (200, 404)

