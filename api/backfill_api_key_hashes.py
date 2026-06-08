"""
Script to populate api_key_hash for existing entries in the api_keys table.

Run AFTER the add_api_key_hash_001 migration:
    python -m api.backfill_api_key_hashes

The script decrypts each API key, calculates the SHA-256 hash, and saves it.
"""

import asyncio
import logging
from sqlalchemy import select
from api.database import AsyncSessionLocal
from api import models, security

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def backfill_hashes():
    async with AsyncSessionLocal() as db:
        # Retrieve all keys without a hash
        result = await db.execute(
            select(models.ApiKey).filter(models.ApiKey.api_key_hash == None)  # noqa: E711
        )
        keys = result.scalars().all()

        logger.info(f"Found {len(keys)} API keys without hash. Starting backfill...")

        updated = 0
        errors = 0

        for key in keys:
            try:
                # Decrypt the key
                plaintext_key = security.decrypt_data(key.encrypted_api_key)
                if not plaintext_key:
                    logger.warning(
                        f"Key ID {key.id}: empty decryption result, skipping"
                    )
                    errors += 1
                    continue

                # Compute the hash
                key_hash = security.hash_data(plaintext_key)

                # Update the entry
                key.api_key_hash = key_hash
                updated += 1

            except Exception as e:
                logger.error(f"Key ID {key.id}: failed to process — {e}")
                errors += 1

        await db.commit()
        logger.info(
            f"Backfill complete: {updated} updated, {errors} errors out of {len(keys)} total"
        )


if __name__ == "__main__":
    asyncio.run(backfill_hashes())
