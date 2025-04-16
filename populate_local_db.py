import json
import os
from pymongo import MongoClient
import logging
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def populate_local_mongodb():
    try:
        # Load environment variables from .env file
        load_dotenv()
        
        # MongoDB connection details
        MONGO_URL = os.getenv("MONGO_URL")
        DB_NAME = os.getenv("DB_NAME", "grantwise")
        COLLECTION_NAME = os.getenv("COLLECTION_NAME", "grants")

        if not MONGO_URL:
            logging.error("MONGO_URL environment variable not set")
            return False

        # Read local grants.json
        with open('grants.json', 'r', encoding='utf-8') as f:
            grants = json.load(f)

        if not grants:
            logging.warning("No grants found in grants.json")
            return False

        # Connect to MongoDB
        client = MongoClient(MONGO_URL)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]

        # Clear existing collection
        collection.delete_many({})
        logging.info("Cleared existing collection")

        # Insert all grants
        result = collection.insert_many(grants)
        logging.info(f"Successfully inserted {len(result.inserted_ids)} grants into MongoDB")

        # Create index on applicationUrl for faster lookups
        collection.create_index("applicationUrl", unique=True)
        logging.info("Created unique index on applicationUrl")

        return True

    except Exception as e:
        logging.error(f"Error populating MongoDB: {str(e)}")
        return False

if __name__ == "__main__":
    if populate_local_mongodb():
        logging.info("Successfully populated MongoDB database")
    else:
        logging.error("Failed to populate MongoDB database")