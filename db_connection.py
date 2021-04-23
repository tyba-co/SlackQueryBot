import json
import boto3
import os

def get_db_params(db):
    """
    Return a dict with the required properties for postgresql connection

    Returns:
      dict with at least the following keys:
      dbName, user, password, host, port
    """
    #TODO: Add your logic to extract your database credentials
    rdscreds = {
      'dbName': 'postgres',
      'user': 'postgres',
      'password': 'postgres',
      'port': 5432,
      'host': 'localhost'
    }
    return rdscreds