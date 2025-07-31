# src/processa_pedido/app.py
import json
import uuid
import os
import boto3
from datetime import datetime

DYNAMODB_TABLE_NAME = os.environ.get("PEDIDOS_TABLE_NAME")

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

def lambda_handler(event, context):
    """
    Função Lambda para processar um pedido.
    Recebe o pedido via API Gateway no formato http e salva em uma tabela DynamoDB.
    """


    try:
        body = json.loads(event['body'])
        
        pedido_id = str(uuid.uuid4())
        item_pedido = body.get('item')
        quantidade = body.get('quantidade')
        
        if not item_pedido or not quantidade:
            return {
                'statusCode': 400,
                'body': json.dumps({'message': 'Item e quantidade são obrigatórios.'})
            }

        status_pedido = "PROCESSANDO"
        current_timestamp = datetime.now().isoformat()

        print(f"Pedido {pedido_id} para {quantidade}x {item_pedido} recebido. Status: {status_pedido} em {current_timestamp}")

        table.put_item(
            Item={
                'pedidoId': pedido_id,
                'timestamp': current_timestamp,
                'item': item_pedido,
                'quantidade': quantidade,
                'status': status_pedido
            }
        )
        
        print(f"Pedido {pedido_id} salvo com sucesso no DynamoDB.")

        # A resposta da Lambda deve seguir o formato de integração proxy
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json'
            },
            'body': json.dumps({
                'message': 'Pedido processado com sucesso!',
                'pedidoId': pedido_id,
                'timestamp': current_timestamp,
                'status': status_pedido
            })
        }

    except json.JSONDecodeError:
        print("Erro: Corpo da requisição inválido (não é um JSON válido).")
        return {
            'statusCode': 400,
            'body': json.dumps({'message': 'Requisição inválida: Corpo deve ser um JSON válido.'})
        }
    except Exception as e:
        print(f"Erro inesperado: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'message': f'Erro interno do servidor: {str(e)}'})
        }