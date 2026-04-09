"""
MongoDB client factory using pymongo.
"""

from pymongo import MongoClient


def create_mongo_client(uri: str) -> MongoClient:
    """
    Create and return a MongoDB client.

    :param uri: MongoDB connection URI
    :return: MongoClient instance
    """
    return MongoClient(uri)