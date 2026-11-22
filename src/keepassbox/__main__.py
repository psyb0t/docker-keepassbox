import uvicorn

from .server import create_app


def main():
    # The container port is published on loopback by the supplied Compose file.
    uvicorn.run(create_app(), host="0.0.0.0", port=8000, access_log=False, proxy_headers=False)  # noqa: S104


if __name__ == "__main__":
    main()
