import requests

from .utils import generate_token


def main():
    server_url = "http://localhost:8080"

    username = input("Enter your username: ")
    password = input("Enter your password: ")

    token = generate_token(username, password)
    print(f"Generated token: {token}")

    response = requests.get(f"{server_url}/", params={"token": token})
    if response.status_code == 200:
        print("File list:")
        print(response.json())
    else:
        print(f"Error: {response.status_code} - {response.json()}")


if __name__ == "__main__":
    main()
