import json
import pymongo
import logging
import os
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

def update_mongodb():
    """Update MongoDB with the latest grants data"""
    try:
        # MongoDB connection details from environment variables
        MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://808dawg:yxSiefIdmoNQoLCK@grantwise.44gsq.mongodb.net/grantwise?retryWrites=true&w=majority")
        DB_NAME = os.getenv("DB_NAME", "grantwise")  # Changed from 'grants' to 'grantwise'
        COLLECTION_NAME = os.getenv("COLLECTION_NAME", "grants")  # Changed from 'grantwise.grants' to 'grants'
        
        logging.info(f"Connecting to MongoDB database: {DB_NAME}")
        
        # Connect to MongoDB with explicit timeout settings
        client = pymongo.MongoClient(
            MONGO_URL,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000
        )
        
        # Test connection
        client.admin.command('ping')
        logging.info("MongoDB connection successful")
        
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]  # Simplified collection access
        logging.info(f"Using collection: {DB_NAME}.{COLLECTION_NAME}")
        
        # Load the latest grants data
        with open('grants.json', 'r', encoding='utf-8') as f:
            grants = json.load(f)
        
        logging.info(f"Loaded {len(grants)} grants from grants.json")
        
        # Track new grants
        existing_titles = set(doc['title'] for doc in collection.find({}, {'title': 1}))
        new_grants = []
        updated_grants = 0
        
        # Process each grant
        for grant in grants:
            # Add a timestamp for when this was added to the database
            grant['last_updated'] = datetime.now().isoformat()
            
            # Check if this is a new grant
            if grant['title'] not in existing_titles:
                new_grants.append(grant)
                collection.insert_one(grant)
            else:
                # Update existing grant
                result = collection.update_one(
                    {'title': grant['title']},
                    {'$set': grant}
                )
                if result.modified_count > 0:
                    updated_grants += 1
        
        logging.info(f"Added {len(new_grants)} new grants to MongoDB")
        logging.info(f"Updated {updated_grants} existing grants in MongoDB")
        
        # Log the titles of new grants
        if new_grants:
            logging.info("New grants added:")
            for grant in new_grants:
                logging.info(f"- {grant['title']}")
        
        return True
    except pymongo.errors.ConnectionFailure as e:
        logging.error(f"Failed to connect to MongoDB: {str(e)}")
        return False
    except Exception as e:
        logging.error(f"Error updating MongoDB: {str(e)}")
        logging.error(f"Error type: {type(e).__name__}")
        return False

if __name__ == "__main__":
    logging.info("=== Starting MongoDB update ===")
    update_mongodb()
    logging.info("=== Completed MongoDB update ===")