import boto3
from .query_logs import QueryLogs

class DynamoLogs(QueryLogs):

    def __init__(self, tablename):
        super().__init__()
        self.dynamoclient = boto3.resource('dynamodb')
        self.table = self.dynamoclient.Table(tablename)

    def register_query(self, id):
        super().register_query(id)
        return self.table.put_item(
            Item={
                'id':  id,
                'authorized': '',
                'author': '',
                'pquery':  '',
                'presult': ''
            }
        )

    def find_query(self, id):
        super().find_query(id)
        return self.table.get_item(
            Key={"id": id}
        )["Item"]

    def apply_lambda_lock(self, id, lambdaId):
        super().apply_lambda_lock(id, lambdaId)
        return self.table.update_item(
            Key={"id": id},
            UpdateExpression='SET lambdaId = :lam1',
            ExpressionAttributeValues={
                ':lam1': lambdaId
            },
            ConditionExpression='attribute_not_exists(lambdaId)'
        )

    def log_query_result(self, id, authorized, author, pquery, presult):
        super().log_query_result(id, authorized, author, pquery, presult)
        return self.table.update_item(
            Key={"id": id},
            UpdateExpression="""SET authorized = :authorized, author = :author,
                            pquery= :pquery, presult = :presult""",
            ExpressionAttributeValues={
            ':authorized': authorized,
            ':author': author,
            ':pquery':  str(pquery),
            ':presult': presult
        })