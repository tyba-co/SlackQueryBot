import json
import boto3
import os
import time
import hashlib
import hmac
import csv
import psycopg2
import re
import time
import db_connection
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from queryLogger.dynamo_logs import DynamoLogs

# Initial Setup
STAGE = os.environ['STAGE']
awsclient = boto3.client('secretsmanager')
dynamoclient = boto3.resource('dynamodb')
authorizedusers = os.environ['AUTHORIZED_USERS'].split(',')
authorizednumber = os.environ['AUTHORIZED_NUMBER']
authorizeddeletenumber = os.environ['AUTHORIZED_DELETE']
queryChannel = os.environ['SLACK_CHANNEL']
dynamoTable = os.environ['DYNAMO_TABLE']
botId = os.environ['BOT_ID']
authorize_reaction = os.environ['AUTH_REACTION']
# Extract Slack credentials from Env Variables
res = json.loads(awsclient.get_secret_value(
    SecretId=os.environ['DUMBO_SECRET'])["SecretString"])
SECRET = res["SECRET"]
TOKEN = res["TOKEN"]
client = WebClient(token=TOKEN)
logger = DynamoLogs(dynamoTable)


def http_response(body='Received', statusCode=200):
    return {
        'statusCode': statusCode,
        'body': body
    }


def get_db_connection(db, channel, ts):
    """Returns the psycopg database connection"""
    pgcreds = db_connection.get_db_params(db)
    try:
        con = psycopg2.connect(
            database=pgcreds["dbName"],
            user=pgcreds["username"],
            password=pgcreds["password"],
            host=pgcreds["host"],
            port=pgcreds["port"])
        return con
    except psycopg2.OperationalError as e:
        client.chat_postMessage(
            channel=channel,
            thread_ts=ts,
            text="Query error, database doesn't exist"
        )
        raise Exception("Query error: "+e)


def process_app_mention(jsonbody):
    """"Process the initial query request"""
    try:
        # Get the message text and extract the query and the db
        logger.register_query(id=jsonbody["event"]["ts"])
        query, db = splitQuery(jsonbody["event"]["text"])
        try:
            con = get_db_connection(
                db, jsonbody["event"]["channel"], jsonbody["event"]["ts"])
        except Exception as e:
            print(e)
            return http_response()

        # Call the chat.postMessage method using the WebClient to notify the query reception
        if jsonbody["event"]["channel"] == queryChannel:
            client.chat_postMessage(
                channel=jsonbody["event"]["channel"],
                thread_ts=jsonbody["event"]["ts"],
                text="Query received, waiting for reactions confirmation"
            )
       # Commented until given correct score
       # userdata = client.users_info(
       #     user=jsonbody['event']['user']
       # )
        userdata = jsonbody['event']['user']
        query = query.replace('&amp;','&').replace('&lt;','<').replace('&gt;','>')

        print(f"Plan to execute '{query}' in {db} sent by {userdata}")
        return http_response()
    except SlackApiError as e:
        print(e)
        client.chat_postMessage(
            channel=jsonbody["event"]["item"]["channel"],
            thread_ts=jsonbody["event"]["item"]["ts"],
            text=f"Slack error: {e}"
        )
        return http_response()
    except Exception as e:
        print(e)
        print("The message syntax is incorrect or drop or truncate found in the query, ignoring this message thread...")


def process_reaction(jsonbody, context):
    """Process a reaction event over the messages"""
    query_id = ''
    channel = ''
    try:
        print(botId)
        print(jsonbody)
        query_id = jsonbody["event"]["item"]["ts"]
        channel = jsonbody["event"]["item"]["channel"]
        # Get all reactions of this message
        info = {"channel": channel,
                "timestamp": query_id}
        result = client.api_call(
            api_method='reactions.get',
            http_verb="GET",
            params=info
        )
        if f'{botId}' not in result["message"]["text"]:
            print('Message not directed to bot, skipping')
            return http_response()
        # In case someone with no authorization makes a reaction, it ignores that
        if jsonbody["event"]["user"] not in authorizedusers:
            print(
                "Somebody different from authorized users reacted, ignoring reaction...")
            return http_response()
        tableresult = logger.find_query(id=query_id)
        if "lambdaId" in tableresult.keys():
            print('Item already in dynamo not running again')
            return http_response()
        # Iterate all reaction types
        for val in result["message"]["reactions"]:
            # Stop in reaction type '100'
            if val["name"] == authorize_reaction:
                users = val["users"]
                count = 0
                accauthorized = []
                # Count amount of authorized users that reacted
                for au in authorizedusers:
                    if au in users:
                        count += 1
                        accauthorized.append(au)
                # If it has at least <authorizednumber> authorized user reactions, approve
                query, db = splitQuery(result["message"]["text"])
                if "drop" in query.lower() or "truncate" in query.lower():
                    authorizednumberfinal = int(authorizeddeletenumber)
                else:
                    authorizednumberfinal = int(authorizednumber)
                if count >= authorizednumberfinal:
                    try:
                        logger.apply_lambda_lock(
                            id=query_id, lambdaId=context.aws_request_id)
                        time.sleep(0.3)
                    except:
                        print('Table locked, not continuing')
                        return http_response()
                    tableresult = logger.find_query(id=query_id)
                    if tableresult['lambdaId'] != context.aws_request_id:
                        print('Table locked, not continuing')
                        return http_response()
                    client.chat_postMessage(
                        channel=channel,
                        thread_ts=query_id,
                        text=f"Query accepted, Executing in {STAGE}"
                    )
                    # if "drop" in query.lower() or "truncate" in query.lower():
                    #     print(f"The query {query} has been denied")
                    #     raise Exception("Query denied")
                    print(
                        f"The users that authorized the query {query} in the database {db} were:")
                    names = []
                    for user in accauthorized:
                        userdata = client.users_info(
                            user=user
                        )
                        print(userdata["user"]["name"])
                        names.append(userdata["user"]["name"])
                    try:
                        con = get_db_connection(db, channel, query_id)
                    except Exception as e:
                        print(e)
                        return http_response()
                    cur = con.cursor()
                    while "<mailto" in query:
                        m = re.search('<mailto:(.+?)>', query)
                        query = re.sub(
                            '<mailto:(.+?)>', m.group(1).split("|")[0], query, 1)
                    query = query.replace('&amp;','&').replace('&lt;','<').replace('&gt;','>')
                    author = client.users_info(
                        user=jsonbody["event"]["item_user"]
                    )
                    try:
                        print(f"executing {query}")
                        cur.execute(query)
                    except Exception as e:
                        client.chat_postMessage(
                            channel=channel,
                            thread_ts=query_id,
                            text=f"Psql Error: {e}"
                        )
                        logger.log_query_result(
                            id=query_id,
                            authorized=",".join(names),
                            author=author["user"]["name"],
                            pquery=str(query),
                            presult=f"Psql Error: {e}"
                        )
                        return http_response()
                    client.chat_postMessage(
                        channel=channel,
                        thread_ts=query_id,
                        text=f"Query executed!"
                    )
                    con.commit()
                    if cur.rowcount >= 0:
                        if query.strip().lower().startswith("select"):
                            pgresult = cur.fetchall()
                            with open('/tmp/file.csv', 'w') as f:
                                writer = csv.writer(f, delimiter=',')
                                for row in pgresult:
                                    writer.writerow(row)
                            try:
                                client.files_upload(
                                    channels=channel,
                                    thread_ts=query_id,
                                    initial_comment="Here's the result of last query statement.",
                                    file='/tmp/file.csv'
                                )
                            except:
                                print("Archivo incompleto")
                        else:
                            pgresult = f"Altered {cur.rowcount} rows"
                            client.chat_postMessage(
                                channel=channel,
                                thread_ts=query_id,
                                text=f"Last statement result: {pgresult}"
                            )
                    con.close()
                    logger.log_query_result(
                        id=query_id,
                        authorized=",".join(names),
                        author=author["user"]["name"],
                        pquery=str(query),
                        presult=str(pgresult)
                    )
                break
        return http_response()
    except SlackApiError as e:
        client.chat_postMessage(
            channel=channel,
            thread_ts=query_id,
            text=f"ERROR: {e}"
        )
        print(f"Error retrieving reactions: {e}")
        return http_response()
    except Exception as e:
        print(e)
        client.chat_postMessage(
            channel=channel,
            thread_ts=query_id,
            text=f"Internal Error: {e}"
        )
        return http_response()


def lambda_handler(event, context):
    """Function that handles incoming hook requests"""
    # Validate if Slack sent the request
    validation = validate(event["body"], event["headers"])
    # validate will return something if it doesn't come from Slack, so finish the execution
    if validation is not None:
        return validation

    if event["httpMethod"] == 'POST':
        jsonbody = json.loads(event["body"])

        # When setting Slack for the first time, it will make a challenge request to bond this hooks server with the api service
        if "challenge" in jsonbody.keys():
            return http_response(body=json.dumps({'challenge': jsonbody["challenge"]}))
        # When someone tags QueryBot in slack (In case someone wants to make a query)
        elif jsonbody["event"]["type"] == "app_mention":
            process_app_mention(jsonbody)
        # When someone reacts to a query message
        elif jsonbody["event"]["type"] == "reaction_added":
            process_reaction(jsonbody, context)
        else:
            return http_response(body='Resource not found', statusCode=404)


def splitQuery(text):
    """Function that process message and returns query and database"""
    maintext = text.replace('\xa0', ' ').split(" ", 1)[1].split("\n", 1)
    query = maintext[1].replace("```", "").replace("\n", " ").strip()
    db = maintext[0].strip()
    return query, db


def validate(body, headers):
    """Validate if incoming requests come exclusively from Slack"""
    if 'X-Slack-Request-Timestamp' not in headers.keys():
        print("This request is not from Slack, exiting...")
        return http_response(statusCode=401)
    else:
        if 'X-Slack-Retry-Num' in headers.keys():
            return http_response()
        # Get request timestamp
        tstamp = headers['X-Slack-Request-Timestamp']
        # Validate if request is not older than 5 minutes
        if abs(time.time() - float(tstamp)) > 60 * 5:
            print("Probably replay attack")
            return http_response(statusCode=401)
        # Actual validation, check https://api.slack.com/authentication/verifying-requests-from-slack#a_recipe_for_security
        sig_basestring = 'v0:' + tstamp + ':' + body
        my_sig = 'v0=' + hmac.new(str.encode(SECRET), msg=str.encode(
            sig_basestring), digestmod=hashlib.sha256).hexdigest()
        slacksignature = headers['X-Slack-Signature']
        if hmac.compare_digest(my_sig, slacksignature):
            print("Slack request validated")
        else:
            print("This request is not from Slack, exiting...")
            return http_response(statusCode=401)
