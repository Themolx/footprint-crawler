"""Entry point for: python -m footprint_crawler"""

import asyncio
import sys

from .cli import main, parse_args

if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    asyncio.run(main(args))
