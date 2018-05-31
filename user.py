import athena
from schema import Schema
from functools import wraps
import json
import boto3
import os
import uuid

# The schema library helps us to ensure the data stored matches a certain schema
from schema import Schema

# We use boto3 to interact with AWS services
s3 = boto3.client('s3')

# This is the environment variable defined in the serverless.yml
BUCKET = os.getenv('BUCKET')
ATHENA_BUCKET = os.getenv('ATHENA_BUCKET')

class S3Model(object):
    """
        This is a base class that will store and load data in an S3 Bucket
        Class attributes:
            - SCHEMA: a schema.Schema instance (https://github.com/keleshev/schema).
                This specify the structure of the data we store
            - name: A string that will define the folder on the S3 bucket
                    in which we will store the file (this will allow for multiple models to be stored on the same bucket)
    """
    
    # By default: All dictionnaries are valid 
    SCHEMA = Schema(dict)
    # The files will be stored in the raw folder
    name = 'raw'

    @classmethod
    def validate(cls, obj):
        assert cls.SCHEMA._schema == dict or type(cls.SCHEMA._schema) == dict
        return cls.SCHEMA.validate(obj)

    @classmethod
    def save(cls, obj):
        # We affect an id if there isn't one
        object_id = obj.setdefault('id', str(uuid.uuid4()))
        obj = cls.validate(obj)
        s3.put_object(
            Bucket=BUCKET,
            Key=f'{cls.name}/{object_id}',
            Body=json.dumps(obj),
        )
        return obj

    @classmethod
    def load(cls, object_id):
        obj = s3.get_object(
            Bucket=BUCKET,
            Key=f'{cls.name}/{object_id}',
        )
        obj = json.loads(obj['Body'].read())
        return cls.validate(obj)

    @classmethod
    def delete_obj(cls, object_id):
        s3.delete_object(
            Bucket=BUCKET,
            Key=f'{cls.name}/{object_id}',
        )
        return {'deleted_id': object_id}

    @classmethod
    def list_ids(cls):
        bucket_content = s3.list_objects_v2(Bucket=BUCKET)

        object_ids = [
            file_path['Key'].lstrip(f'{cls.name}/')
            for file_path in bucket_content.get('Contents', [])
            if file_path['Size'] > 0
        ]

        return object_ids


def handle_api_error(func):
    """
        This define a decorator to format the HTTP response of the lambda:
        - a status code
        - the body of the response as a string
    """

    @wraps(func)
    def wrapped_func(*args, **kwargs):
        try:
            return {
                'statusCode': 200,
                'body': json.dumps(func(*args, **kwargs)),
            }
        except Exception as e:
            return {
                'statusCode': 500,
                'body': str(e),
            }
    return wrapped_func


class S3ApiRaw(object):
    """
        A class providing the lambda handlers for the HTTP requests of an S3Model class
        Class attribute:
         - s3_model_cls: an S3Model class providing the schema of the object and the helper functions to mange the S3 data
    """
    s3_model_cls = S3Model

    @classmethod
    @handle_api_error
    def get(cls, event, context):
        obj_id = event['pathParameters']['id']
        return cls.s3_model_cls.load(obj_id)

    @classmethod
    @handle_api_error
    def put(cls, event, context):
        obj_id = event['pathParameters']['id']
        obj = cls.s3_model_cls.load(obj_id)

        updates = json.loads(event['body'])
        obj.update(updates)

        return cls.s3_model_cls.save(obj)

    @classmethod
    @handle_api_error
    def post(cls, event, context):
        obj = json.loads(event['body'])
        if 'id' in obj:
            raise Exception('Do not specify id in resource creation')
        return cls.s3_model_cls.save(obj)

    @classmethod
    @handle_api_error
    def delete(cls, event, context):
        obj_id = event['pathParameters']['id']
        return cls.s3_model_cls.delete_obj(obj_id)

    @classmethod
    @handle_api_error
    def all(cls, event, context):
        return [cls.s3_model_cls.load(obj_id) for obj_id in cls.s3_model_cls.list_ids()]

    # This method is a little bit clumsy but we need the lambda handlers to be module functions
    @classmethod
    def get_api_methods(self):
        return self.get, self.post, self.put, self.delete, self.all

# We define the model
class User(S3Model):
    """
        User:
        - name: "user"
        - schema:
           id: string
           first_name: str,
           last_name: str,
           birthday: str,
    """
    name = 'user'
    SCHEMA = Schema({
        'id': str,
        'first_name': str,
        'last_name': str,
        'birthday': str,
    })


# Next we define the resource
class UserResource(S3ApiRaw):
    s3_model_cls = User

# Finally we declare the lambda handlers as module functions
get, post, put, delete, _ = UserResource.get_api_methods()

@handle_api_error
def all(event, context):
    users = athena.get_results(f"""
        SELECT * FROM {athena.DB}.users
    """)
    return users