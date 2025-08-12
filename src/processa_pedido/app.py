# src/processa_pedido/app.py
import json
import uuid
import os
import boto3
from datetime import datetime
from typing import Dict, Literal, List
from pydantic import BaseModel, ValidationError, Field

DYNAMODB_TABLE_NAME = os.environ.get("PEDIDOS_TABLE_NAME")

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

class ItemPedido(BaseModel):
    """Define os detalhes de um item, cujo ID é a chave do dicionário."""
    nome: str
    preco_unitario: float = Field(gt=0, description="O preço deve ser maior que zero")
    quantidade: int = Field(gt=0, description="A quantidade deve ser maior que zero")

class Pedido(BaseModel):
    """Define a estrutura do corpo da requisição para um novo pedido."""
    items: Dict[str, ItemPedido] = Field(..., description="Dicionário de itens do pedido, onde a chave é o ID do item")
    clienteId: str = Field(..., description="ID do cliente que está fazendo o pedido")
    enderecoEntrega: str = Field(..., description="Endereço de entrega do pedido")
    paymentMethod: Literal['CARTAO_CREDITO', 'CARTAO_DEBITO', 'PIX']

def lambda_handler(event, context):
    """
    Função Lambda para registrar um pedido de um cliente.
    1. Recebe o pedido via API Gateway no formato http 
    2. Valida o pedido
    3. Salva o pedido em uma tabela DynamoDB.
    """

    try:
        # 1. Parse e validação em um único passo com Pydantic
        body_data = json.loads(event.get('body', '{}'))
        pedido_validado = Pedido(**body_data)
        
        pedido_id = str(uuid.uuid4())
        status_pedido = "PENDENTE"
        current_timestamp = datetime.now().isoformat()
        total = sum(item.preco_unitario * item.quantidade for item in pedido_validado.items.values())

        itens_resumo = ", ".join([f"{item.quantidade}x {item.nome}" for item_id, item in pedido_validado.items.items()])
        print(f"Pedido {pedido_id} contendo [{itens_resumo}] recebido. Status: {status_pedido} em {current_timestamp}")

        # 2. Monta o item para o DynamoDB a partir do modelo validado
        dynamo_order = {
            'pedidoId': pedido_id,
            'timestamp': current_timestamp,
            'status': status_pedido,
            'total': total,
            **pedido_validado.model_dump() # Converte o modelo Pydantic para um dict
        }
        
        table.put_item(
            Item=dynamo_order
        )
        
        print(f"Pedido {pedido_id} salvo com sucesso no DynamoDB.")

        # 3. Retorna uma resposta de sucesso
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
    except ValidationError as e:
        # Pydantic levanta ValidationError com detalhes sobre os campos inválidos
        print(f"Erro de validação: {e.errors()}")
        return {
            'statusCode': 400, # Bad Request
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'message': 'Dados de entrada inválidos.', 'details': e.errors()})
        }
    except Exception as e:
        print(f"Erro inesperado: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'message': f'Erro interno do servidor: {str(e)}'})
        }
