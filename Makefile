TERMINAL = wt

test:
	pytest tests

test_server:
	pytest tests/test_server.py

test_client:
	pytest tests/test_client.py

