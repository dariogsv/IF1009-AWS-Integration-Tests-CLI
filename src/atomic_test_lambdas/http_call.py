import json
import requests
import os

def lambda_handler(event, context):
    """
    Lambda atômica para executar qualquer chamada HTTP/API Gateway.
    Input: { "testRunId": "...", "action_params": { "url": "...", "method": "...", "headers": {}, "body": {} } }
    Output: { "status": "SUCCESS/FAILED", "result": {...}, "statusCode": ... }
    """
    test_run_id = event.get('testRunId', 'N/A')
    action_params = event.get('action_params', {})

    url = action_params.get('url')
    method = action_params.get('method', 'GET').upper()
    headers = action_params.get('headers', {'Content-Type': 'application/json'})
    request_body = action_params.get('body')
    expected_status_code = action_params.get('expectedStatusCode', None) # Para validação interna se desejar

    if not url:
        raise ValueError(f"[{test_run_id}] URL é obrigatória para chamada HTTP.")

    try:
        print(f"[{test_run_id}] HTTP_CALL: {method} {url} com body: {json.dumps(request_body)}")
        response = requests.request(
            method,
            url,
            headers=headers,
            json=request_body if request_body and isinstance(request_body, dict) else None,
            data=json.dumps(request_body) if request_body and not isinstance(request_body, dict) else None, # Para raw JSON
            timeout=20
        )
        
        response_json = response.json() if response.content else {} # Tenta parsear JSON se houver conteúdo

        print(f"[{test_run_id}] HTTP_CALL: Resposta status {response.status_code}: {json.dumps(response_json)}")

        # Validação simples interna da Lambda (opcional, pode ser feita na Step Functions)
        if expected_status_code is not None and response.status_code != expected_status_code:
            return {'status': 'FAILED', 'message': f'Esperado status {expected_status_code}, recebido {response.status_code}', 'result': response_json, 'statusCode': response.status_code}

        return {'status': 'SUCCESS', 'result': response_json, 'statusCode': response.status_code}

    except requests.exceptions.Timeout:
        raise Exception(f"[{test_run_id}] HTTP_CALL Erro: Timeout ao chamar a API: {url}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"[{test_run_id}] HTTP_CALL Erro na requisição HTTP para {url}: {str(e)}")
    except json.JSONDecodeError:
        print(f"[{test_run_id}] HTTP_CALL Aviso: Resposta não é um JSON válido. Conteúdo: {response.text[:100]}...")
        return {'status': 'SUCCESS', 'result': response.text, 'statusCode': response.status_code} # Retorna o texto bruto se não for JSON
    except Exception as e:
        raise Exception(f"[{test_run_id}] HTTP_CALL Erro inesperado: {str(e)}")