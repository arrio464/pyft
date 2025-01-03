TERMINAL = wt

test:
	pytest tests

test-server:
	pytest tests/test_server.py

test-client:
	pytest tests/test_client.py

run: run-server run-clients

run-server:
	echo "Starting server..."
	$(TERMINAL) --window _pyft new-tab --title "Server" --command pdm run python -m src.pyft.server

run-clients:
	echo "Starting clients..."
	$(TERMINAL) --window _pyft new-tab --title "Client" --command pdm run python -m src.pyft.client -u user1 -p password1