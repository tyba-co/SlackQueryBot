from abc import ABC, abstractmethod

class QueryLogs(ABC):

    @abstractmethod
    def __init__(self):
        pass

    @abstractmethod
    def register_query(self, id):
        print(f"Registering new query with id: {id}")
        pass

    @abstractmethod
    def find_query(self, id):
        pass

    @abstractmethod
    def apply_lambda_lock(self, id, lambdaId):
        print(f'trying to lock query {id} to lambda {lambdaId}')
        pass

    @abstractmethod
    def log_query_result(self, id, authorized, author, pquery, presult):
        print(f'Logging query result for query {id}')
        pass
