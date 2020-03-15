import asyncio

from dvsportal import DVSPortal


async def main(loop):
    """Show example on fetching permits from DVSPortal."""
    async with DVSPortal(api_host="parkeervergunning.enschede.nl",
                         identifier="<identifier>",
                         password="<password>",
                         loop=loop) as dvs:
        token = await dvs.token()
        print("Token:", token)
        await dvs.update()
        permits = await dvs.permits()
        print("Permits:", permits)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(loop))
