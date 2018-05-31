import os
import boto3
from time import sleep

# This is the new bucket that stores the query results
ATHENA_BUCKET = os.getenv('ATHENA_BUCKET', 'bucket')
BUCKET = os.getenv('BUCKET', 'bucket')
DB = f'{BUCKET.replace("-","_")}'
athena = boto3.client('athena')


# This is the function that start the execution and get the results
def get_results(query, database=DB):
    query_id = hash(query)

    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={
            'Database': database
        },
        ResultConfiguration={
            'OutputLocation': f's3://{ATHENA_BUCKET}/{query_id}'
        }
    )

    results = get_query_results(response['QueryExecutionId'])
    return results


#This function polls the state of the query execution each second and fetches the results once it's finished
def get_query_results(exec_id):

    while(not is_execution_done(exec_id)):
        print('not done yet')
        sleep(1)

    results = athena.get_query_results(
        QueryExecutionId=exec_id,
    )
    print(results)

    return format_result(results)

# This function checks the state of the execution, returns true if it is SUCCEEDED
def is_execution_done(exec_id):
    response = athena.get_query_execution(
        QueryExecutionId=exec_id,
    )
    if response['QueryExecution']['Status']['State'] == 'FAILED':
        raise Exception('Failed Athena query')

    return response['QueryExecution']['Status']['State'] == 'SUCCEEDED'

# This functions just parses the rows and return a list of dictionnaries
def format_result(results):

    columns = [
        col['Label']
        for col in results['ResultSet']['ResultSetMetadata']['ColumnInfo']
    ]

    formatted_results = []

    for result in results['ResultSet']['Rows'][1:]:
        values = [list(field.values())[0] for field in result['Data']]

        formatted_results.append(
            dict(zip(columns, values))
        )

    return formatted_results


def init_schema(event, context):
    db = get_results(f"""
        CREATE DATABASE IF NOT EXISTS {DB}
        LOCATION 's3://{BUCKET}/';
    """, 'default')

    table = get_results(f"""
        CREATE EXTERNAL TABLE IF NOT exists users (
            id STRING,
            first_name STRING,
            last_name STRING,
            birthday STRING
        )
        ROW FORMAT  serde 'org.openx.data.jsonserde.JsonSerDe'
        with serdeproperties ( 'paths'='id, first_name, last_name, birthday' )
        LOCATION 's3://{BUCKET}/';
    """)

    return db, table