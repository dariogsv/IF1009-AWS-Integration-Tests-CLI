import json
import boto3
import os

# Inicializa clientes Lambda para invocar as Lambdas atômicas
lambda_client = boto3.client('lambda')

# Mapeia tipos de ação para os ARNs das Lambdas atômicas
# Estes ARNs serão passados via variáveis de ambiente para esta Lambda
HTTP_CALL_LAMBDA_ARN = os.environ.get('HTTP_CALL_LAMBDA_ARN')
LAMBDA_INVOKE_LAMBDA_ARN = os.environ.get('LAMBDA_INVOKE_LAMBDA_ARN')
DYNAMODB_INTERACT_LAMBDA_ARN = os.environ.get('DYNAMODB_INTERACT_LAMBDA_ARN')
# ... adicione outros ARNs conforme mais Lambdas atômicas forem criadas

def lambda_handler(event, context):
    """
    Lambda central que invoca as Lambdas de teste atômicas com base no actionType.
    Input: { "testRunId": "...", "actionType": "http_call", "actionName": "...", "action_params": {...}, "contextData": {...} }
    """
    test_run_id = event.get('testRunId', 'N/A')
    action_type = event.get('actionType')
    action_name = event.get('actionName', 'Unnamed Action')
    action_params = event.get('action_params', {})
    context_data = event.get('contextData', {}) # Dados do estado da SFN para usar em validações/limpeza

    print(f"[{test_run_id}] Executando ação atômica '{action_name}' ({action_type})...")

    # Payload que será passado para a Lambda atômica específica
    payload_to_atomic_lambda = {
        'testRunId': test_run_id,
        'action_params': action_params,
        'contextData': context_data # Passa o contexto para que Lambdas atômicas possam acessar resultados anteriores
    }

    target_lambda_arn = None
    if action_type == "http_call":
        target_lambda_arn = HTTP_CALL_LAMBDA_ARN
    elif action_type == "lambda_invoke":
        target_lambda_arn = LAMBDA_INVOKE_LAMBDA_ARN
    elif action_type == "dynamodb_interact":
        target_lambda_arn = DYNAMODB_INTERACT_LAMBDA_ARN
    # Adicione mais tipos de ação aqui
    elif action_type == "verify_assertions": # Lógica de asserção final
        return _verify_assertions(test_run_id, action_params, context_data)
    else:
        raise ValueError(f"[{test_run_id}] Tipo de ação atômica não suportado: {action_type}")

    if not target_lambda_arn:
        raise Exception(f"[{test_run_id}] ARN da Lambda para a ação '{action_type}' não configurado.")

    try:
        response = lambda_client.invoke(
            FunctionName=target_lambda_arn,
            InvocationType='RequestResponse',
            Payload=json.dumps(payload_to_atomic_lambda)
        )
        
        response_payload = json.loads(response['Payload'].read().decode('utf-8'))

        if 'FunctionError' in response:
            error_message = response_payload.get('errorMessage', 'Erro desconhecido na função Lambda atômica invocada.')
            error_type = response_payload.get('errorType', 'AtomicLambdaInvokeError')
            raise Exception(f"[{test_run_id}] Erro na Lambda atômica '{action_type}': {error_type} - {error_message}")

        return response_payload # Retorna o resultado da Lambda atômica

    except Exception as e:
        print(f"[{test_run_id}] Erro ao invocar Lambda atômica {action_type}: {e}")
        raise # Re-lança para a Step Functions

# --- Função de Asserção Final (pode ser parte da atomic_lambda_invoker ou uma Lambda separada) ---
def _verify_assertions(test_run_id, assertions_config, context_data):
    """
    Realiza as asserções finais do teste com base nos resultados das ações.
    assertions_config: { "type": "...", "params": {...}, "expected_value": "..." }
    context_data: o payload do Map state, contendo os resultados de todas as ações.
    """
    print(f"[{test_run_id}] VERIFY_ASSERTIONS: Iniciando validação final...")
    
    # Exemplo de como acessar resultados de ações anteriores:
    # Digamos que a primeira ação foi um http_call e a segunda foi um dynamodb_interact (get_item)
    # api_call_result = context_data[0].get('actionResult', {}).get('result', {})
    # db_get_result = context_data[1].get('actionResult', {}).get('result', {})

    # Você precisará de uma lógica flexível para percorrer 'assertions_config'
    # e verificar os dados em 'context_data'.
    # Isso pode envolver expressões JMESPath ou simplesmente lógica Python.

    all_assertions_passed = True
    failed_assertions = []

    for assertion in assertions_config.get('checks', []):
        assertion_type = assertion.get('type')
        assertion_params = assertion.get('params', {})
        
        if assertion_type == "api_response_status":
            # Exemplo: Verificar o status HTTP da primeira chamada de API
            action_index = assertion_params.get('actionIndex', 0) # Qual ação do array 'actions'
            expected_status = assertion_params.get('expectedStatus')
            actual_status = context_data[action_index].get('actionResult', {}).get('statusCode')
            
            if actual_status != expected_status:
                all_assertions_passed = False
                failed_assertions.append(f"API status check failed for action {action_index}. Expected {expected_status}, got {actual_status}.")
        
        elif assertion_type == "db_item_value":
            # Exemplo: Verificar um valor em um item de DB obtido
            action_index = assertion_params.get('actionIndex', 0) # Qual ação do array 'actions' (se foi um get_item ou query)
            expected_key = assertion_params.get('key')
            expected_value = assertion_params.get('expectedValue')

            db_item = context_data[action_index].get('actionResult', {}).get('result') # Se get_item retornou o item
            
            if not db_item or db_item.get(expected_key) != expected_value:
                all_assertions_passed = False
                failed_assertions.append(f"DB item value check failed for action {action_index}. Expected {expected_key}={expected_value}, got {db_item.get(expected_key) if db_item else 'None'}.")

        # Adicione mais tipos de asserção (e.g., SQS message count, S3 object existence)
        
    if all_assertions_passed:
        print(f"[{test_run_id}] VERIFY_ASSERTIONS: Todas as asserções passaram.")
        return {'status': 'PASSED', 'details': 'Todas as asserções foram bem-sucedidas.'}
    else:
        print(f"[{test_run_id}] VERIFY_ASSERTIONS: Algumas asserções falharam: {failed_assertions}")
        return {'status': 'FAILED', 'details': json.dumps(failed_assertions)}