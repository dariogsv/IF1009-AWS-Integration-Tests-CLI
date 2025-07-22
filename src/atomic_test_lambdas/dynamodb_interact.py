import json
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key # Para Query

dynamodb = boto3.resource('dynamodb')

def lambda_handler(event, context):
    """
    Lambda atômica para interagir com DynamoDB (Put, Get, Query, Delete).
    Input: { "testRunId": "...", "action_params": { "table_name": "...", "action": "put_item", "item": {...} } }
    """
    test_run_id = event.get('testRunId', 'N/A')
    action_params = event.get('action_params', {})

    table_name = action_params.get('table_name')
    action = action_params.get('action') # put_item, get_item, query, delete_item
    params = action_params.get('params', {}) # Parâmetros específicos da ação DynamoDB

    if not table_name or not action:
        raise ValueError(f"[{test_run_id}] table_name e action são obrigatórios para DynamoDB.")

    table = dynamodb.Table(table_name)
    
    print(f"[{test_run_id}] DYNAMODB_INTERACT: Tabela {table_name}, Ação {action} com params: {json.dumps(params)}")

    try:
        if action == "put_item":
            item = params.get('item')
            if not item: raise ValueError("Item é obrigatório para put_item.")
            response = table.put_item(Item=item)
            return {'status': 'SUCCESS', 'action': 'put_item', 'result': response}

        elif action == "get_item":
            key = params.get('key')
            if not key: raise ValueError("Key é obrigatória para get_item.")
            response = table.get_item(Key=key)
            return {'status': 'SUCCESS', 'action': 'get_item', 'result': response.get('Item')}

        elif action == "query":
            key_condition_expression_str = params.get('keyConditionExpression')
            expression_attribute_values = params.get('expressionAttributeValues')
            
            if not key_condition_expression_str or not expression_attribute_values:
                raise ValueError("keyConditionExpression e expressionAttributeValues são obrigatórios para query.")
            
            # ATENÇÃO: Construir KeyConditionExpression dinamicamente é mais complexo.
            # Para simplificar neste exemplo, esperamos que a string seja algo como "pedidoId = :val"
            # e a Lambda apenas invoca a query com ela. Para produção, considere um parser de KCE.
            
            # Exemplo SIMPLIFICADO de como converter string KCE para objeto Key
            # Este é um placeholder, para expressões complexas, precisaria de um parser real.
            # Para seu projeto, foque em igualdade simples ou use o nome do campo.
            key_parts = key_condition_expression_str.split(' ')
            if len(key_parts) == 3 and key_parts[1] == '=':
                key_condition_expression = Key(key_parts[0]).eq(expression_attribute_values[key_parts[2]])
            else:
                raise ValueError("KeyConditionExpression muito complexa para parser simples.")


            response = table.query(
                KeyConditionExpression=key_condition_expression,
                ExpressionAttributeValues=expression_attribute_values,
                **{k:v for k,v in params.items() if k not in ['keyConditionExpression', 'expressionAttributeValues', 'action', 'table_name']} # Passa outros parâmetros da query
            )
            return {'status': 'SUCCESS', 'action': 'query', 'result': response.get('Items')}

        elif action == "delete_item":
            key = params.get('key')
            if not key: raise ValueError("Key é obrigatória para delete_item.")
            response = table.delete_item(Key=key)
            return {'status': 'SUCCESS', 'action': 'delete_item', 'result': response}

        else:
            raise ValueError(f"Ação DynamoDB não suportada: {action}")

    except ClientError as e:
        raise Exception(f"[{test_run_id}] DYNAMODB_INTERACT Erro AWS: {e}")
    except Exception as e:
        raise Exception(f"[{test_run_id}] DYNAMODB_INTERACT Erro inesperado: {str(e)}")