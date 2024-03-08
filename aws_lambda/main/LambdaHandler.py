import json
import datetime
import boto3
import urllib3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key

HTTP_GET_METHOD = 'GET'
HTTP_POST_METHOD = 'POST'

# Secrets Manager
def get_secret_api_key():
    secret_name = "prod/api/key/chatgpt"
    secret_key = "api-key-chatgpt"
    region_name = "us-east-1"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e

    # Decrypts secret using the associated KMS key.
    secret_response = get_secret_value_response[ 'SecretString' ]
    secret_object = json.loads(secret_response) 
    secret_api_key = secret_object['api-key-chatgpt']
    
    # Return secret
    return secret_api_key
    
def mask_value(str):
    new_str = ""
    for i in range(len(str)):
        if i <  7:
            new_str += str[i]
        else:
            new_str += '*'
    return new_str
    
# DynamoDb
def get_conversation_history(user_key):
    dynamoDb = boto3.resource('dynamodb')
    table = dynamoDb.Table('Video-000200-UserConversation')
    response = table.query(
        KeyConditionExpression=Key('userKey').eq(user_key)
    )
    return response['Items']

def save_conversation_history(user_key,question,answer):
    date_time = datetime.datetime.now()
    date_time_str = date_time.strftime('%Y-%m-%d %H:%M:%S.%f')
    item_object = {}
    item_object['userKey'] = user_key
    item_object['dateTime'] = date_time_str
    item_object['question'] = question
    item_object['answer'] = answer
    dynamoDb = boto3.resource('dynamodb')
    table = dynamoDb.Table('Video-000200-UserConversation')
    response = table.put_item( Item=item_object )
    
def build_payload(next_question,user_conversation_items):
    messages = []
    
    # Add the base message plus the previous user conversation
    messages.append({"role": "system", "content": f"You are an assistant who answers questions about the world."})
    for user_conversation_item in user_conversation_items:
        json_object = {}
        json_object['role'] = 'user'
        json_object['content'] = user_conversation_item['question']
        messages.append(json_object)
        
        json_object = {}
        json_object['role'] = 'assistant'
        json_object['content'] = user_conversation_item['answer']
        messages.append(json_object)
        
    # Add the next user question
    json_object = {}
    json_object['role'] = 'user'
    json_object['content'] = next_question
    messages.append(json_object)
        
    # Construct the payload
    payload = {
        "model": "gpt-3.5-turbo",
        "temperature" : 1.0,
        "messages" : messages
    }
    return payload
    
def extract_answer_from_response(response):
    response_dictionary = json.loads(response.data.decode('utf-8'))
    choices = response_dictionary['choices']
    choice = choices[0]
    message = choice['message']
    answer = message['content']
    return answer


# REST API Handling
def handle_get_request(event):
    print("Handle_get_request-begin")
    user_key = str(event['queryStringParameters']['userKey'])
    print("Get UserKey->" + user_key )
    
    # get conversation history
    user_conversation_items = get_conversation_history(user_key)
    
    # log
    print("Handle_get_request-end")
    
    # return conversation history
    return user_conversation_items
    
def handle_post_request(event):
    print("Handle_post_request-begin")
    json_body = json.loads(event['body'])
    user_key = str(json_body['userKey'])
    chat_question = str(json_body['chatQuestion'])
    print("Post UserKey->" + user_key )
    print("Post ChatQuestion->" + chat_question )
    
    api_key = get_secret_api_key()
    masked_api_key = mask_value( api_key )
    print( masked_api_key )
    
    # Initialize key variables
    OPEN_AI_CHATGPT_URL = "https://api.openai.com/v1/chat/completions"
    HEADERS = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
    }
    
    # get conversation history
    user_conversation_items = get_conversation_history(user_key)

    # build prompt for ChatGPT
    print("QUESTION--->" + chat_question)
    payload = build_payload(chat_question,user_conversation_items)
    encoded_payload = json.dumps(payload)

    # make request to ChatGPT and get response
    http = urllib3.PoolManager()
    response = http.request('POST',
                             OPEN_AI_CHATGPT_URL,
                             headers=HEADERS,
                             body=encoded_payload)
    chat_answer = extract_answer_from_response(response)
    print("ANSWER--->" + chat_answer + "\n" )
    
    # Save conversation
    save_conversation_history(user_key,chat_question,chat_answer)
    
    # get conversation history
    user_conversation_items = get_conversation_history(user_key)
    
    # Log
    print("Handle_post_request-end")
    
    # return conversation history
    return user_conversation_items
    

def lambda_handler(event, context):
    
    print("Lambda_handler-begin")
    print( event )
    
    method = event['httpMethod']
    
    if method == HTTP_GET_METHOD:
        user_conversation_items = handle_get_request(event)
        
    elif method == HTTP_POST_METHOD:
        user_conversation_items = handle_post_request(event)
        
    else:
        print( "Unspported Method->" + method )
        user_conversation_items = []
        
    print("Lambda_handler-end")
    
    # TODO implement
    return {
        'statusCode': 200,
        "headers": {
            "Access-Control-Allow-Origin": "*"
        },
        'body': json.dumps(user_conversation_items)
    }