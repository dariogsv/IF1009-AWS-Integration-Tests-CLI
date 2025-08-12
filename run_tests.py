import boto3
import json
import time
import os
from pathlib import Path
import click

sfn_client = boto3.client('stepfunctions')

def monitor_execution(execution_arn: str) -> str:
    """Espera a execução da Step Function terminar e retorna o status final."""
    while True:
        try:
            result = sfn_client.describe_execution(executionArn=execution_arn)
            status = result['status']
            if status in ['SUCCEEDED', 'FAILED', 'TIMED_OUT', 'ABORTED']:
                if status == 'FAILED':
                    history = sfn_client.get_execution_history(
                        executionArn=execution_arn,
                        reverseOrder=True,
                        maxResults=1
                    )
                    fail_details = history['events'][0].get('executionFailedEventDetails', {})
                    error = fail_details.get('error', 'UnknownError')
                    cause = fail_details.get('cause', 'UnknownCause')
                    click.secho(f"  ├─ Error: {error}", fg="red")
                    click.secho(f"  └─ Cause: {cause}", fg="red")
                return status
            time.sleep(3)  # Poll a cada 3 segundos
        except sfn_client.exceptions.ExecutionDoesNotExist:
            click.secho(f"Erro: Execução {execution_arn} não encontrada.", fg="red")
            return "FAILED"

@click.command()
@click.option('--sfn-arn', required=True, help='ARN da State Machine de teste a ser executada.')
@click.option('--tests-dir', default='tests', help='Diretório contendo os arquivos de cenário .json.')
def run(sfn_arn, tests_dir):
    """Orquestrador de testes que executa uma Step Function para cada cenário .json."""
    all_json_files = Path(tests_dir).glob('*.json')
    # Filtra para não incluir arquivos de definição de Step Function (.asl.json)
    test_files = sorted([f for f in all_json_files if not f.name.endswith('.asl.json')])

    if not test_files:
        click.secho(f"Nenhum arquivo de teste .json encontrado em '{tests_dir}'.", fg="yellow")
        return

    click.secho(f"Encontrados {len(test_files)} cenários de teste.", fg="blue")

    for test_file in test_files:
        with open(test_file, 'r', encoding='utf-8') as f:
            test_case = json.load(f)

        click.echo(f"▶️  Executando teste: {click.style(test_file.name, bold=True)}")
        response = sfn_client.start_execution(
            stateMachineArn=sfn_arn,
            input=json.dumps(test_case)
        )
        status = monitor_execution(response['executionArn'])
        fg_color = "green" if status == 'SUCCEEDED' else "red"
        click.secho(f"   Resultado: {status}\n", fg=fg_color)

if __name__ == '__main__':
    run()
