import json
import boto3

lambda_client = boto3.client('lambda')

def lambda_handler(event, context):
    """
    Lambda atômica para invocar outra função Lambda.
    Input: { "testRunId": "...", "action_params": { "function_name": "...", "payload": {...} } }
    Output: { "status": "SUCCESS/FAILED", "result": {...} }
    """
    test_run_id = event.get('testRunId', 'N/A')
    action_params = event.get('action_params', {})

    function_name = action_params.get('function_name')
    payload = action_params.get('payload', {})
    
    if not function_name:
        raise ValueError(f"[{test_run_id}] function_name é obrigatório para invocar Lambda.")

    try:
        print(f"[{test_run_id}] LAMBDA_INVOKE: Invocando função {function_name} com payload: {json.dumps(payload)}")
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse', # Para obter a resposta de volta
            Payload=json.dumps(payload)
        )
        
        response_payload = json.loads(response['Payload'].read().decode('utf-8'))
        
        # Verifica se a Lambda invocada retornou um erro
        if 'FunctionError' in response:
            error_message = response_payload.get('errorMessage', 'Erro desconhecido na função Lambda invocada.')
            error_type = response_payload.get('errorType', 'LambdaInvokeError')
            raise Exception(f"[{test_run_id}] LAMBDA_INVOKE Erro na função invocada: {error_type} - {error_message}")

        print(f"[{test_run_id}] LAMBDA_INVOKE: Resposta da função {function_name}: {json.dumps(response_payload)}")
        return {'status': 'SUCCESS', 'result': response_payload}

    except ClientError as e:
        raise Exception(f"[{test_run_id}] LAMBDA_INVOKE Erro AWS ao invocar Lambda: {e}")
    except Exception as e:
        raise Exception(f"[{test_run_id}] LAMBDA_INVOKE Erro inesperado: {str(e)}")