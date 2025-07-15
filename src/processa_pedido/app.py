# src/processa_pedido/app.py
import json
import os
import uuid
import boto3
from datetime import datetime

DYNAMODB_TABLE_NAME = "PedidoServiceSam-Pedidos" # Confirme que o nome aqui corresponde ao template!

dynamodb = boto3.resource('dynamodb')

def lambda_handler(event, context):
    """
    Função Lambda para processar um pedido.
    Recebe o pedido via API Gateway (agora via proxy novamente para simulação local)
    e salva o status em uma tabela DynamoDB.
    """
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)

    try:
        # AQUI É A MUDANÇA: Voltamos a acessar o corpo da requisição via event['body']
        # porque a integração Type: Api do SAM usa integração proxy por padrão para simulação local.
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