#!/usr/bin/env python3
import argparse
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=57384)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    uvicorn.run(
        "backend.server:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_level="info",
    )
