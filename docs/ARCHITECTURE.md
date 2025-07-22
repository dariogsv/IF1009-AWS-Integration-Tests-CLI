# Architecture Documentation

## System Architecture Overview

The AWS Integration Tests CLI is built on a serverless architecture using AWS Step Functions to orchestrate end-to-end tests across microservices.

## Component Architecture

### 1. CLI Layer
The command-line interface provides user interaction capabilities:

```mermaid
classDiagram
    class CLI {
        +run(scenario_name, state_machine_arn, wait)
        +status(execution_arn)
        +logs(execution_arn)
        +list_scenarios()
        -_load_scenario(scenario_name)
        -_get_sfn_execution_details(execution_arn)
        -_log_message(message, level)
    }
    
    class ClickCommands {
        <<interface>>
        +run()
        +status()
        +logs()
        +list_scenarios()
    }
    
    class AWSClients {
        +sfn_client
        +logs_client
    }
    
    CLI --> ClickCommands
    CLI --> AWSClients
```

### 2. Test Orchestration Layer

```mermaid
graph TB
    subgraph "Step Functions State Machine"
        START[PrepareAndExecuteActions]
        MAP[Map State - Sequential Execution]
        ATOMIC[ExecuteAtomicAction]
        CHOICE[HandleActionResult]
        VERIFY[VerifyFinalAssertions]
        CLEANUP[CleanUpTestData]
        SUCCESS[TestSucceeded]
        FAIL[TestFailed]
        
        START --> MAP
        MAP --> ATOMIC
        ATOMIC --> CHOICE
        CHOICE -->|Success| VERIFY
        CHOICE -->|Failure| FAIL
        VERIFY --> CLEANUP
        CLEANUP --> SUCCESS
    end
```

### 3. Atomic Actions Layer

The atomic actions provide modular test capabilities:

```mermaid
classDiagram
    class AtomicLambdaInvoker {
        +lambda_handler(event, context)
        -dispatch_action(action_type, params, context_data)
    }
    
    class HTTPCallAction {
        +execute(params, context_data)
        -make_request(url, method, headers, body)
        -validate_response(response, expected_status)
    }
    
    class DynamoDBAction {
        +execute(params, context_data)
        -get_item(table, key)
        -put_item(table, item)
        -query(table, conditions)
    }
    
    class LambdaInvokeAction {
        +execute(params, context_data)
        -invoke_function(function_name, payload)
        -process_response(response)
    }
    
    AtomicLambdaInvoker --> HTTPCallAction
    AtomicLambdaInvoker --> DynamoDBAction
    AtomicLambdaInvoker --> LambdaInvokeAction
```

## Data Flow Architecture

### Test Execution Data Flow

```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant S3 as Test Scenarios
    participant SFN as Step Functions
    participant AL as Atomic Lambda
    participant Target as Target Services
    participant CW as CloudWatch
    
    User->>CLI: Execute test scenario
    CLI->>S3: Load scenario JSON
    S3-->>CLI: Test configuration
    CLI->>SFN: Start execution with config
    
    loop For each action in scenario
        SFN->>AL: Execute atomic action
        AL->>Target: Perform action (HTTP/DB/Lambda)
        Target-->>AL: Action result
        AL->>CW: Log action details
        AL-->>SFN: Return result
    end
    
    SFN->>AL: Verify assertions
    AL-->>SFN: Verification result
    SFN->>CW: Log execution summary
    SFN-->>CLI: Execution complete
    CLI-->>User: Display results
```

## State Management

### Test Context Flow

```mermaid
stateDiagram-v2
    [*] --> TestInitialized: Load scenario
    TestInitialized --> ActionExecuting: Start first action
    ActionExecuting --> ActionCompleted: Action succeeds
    ActionExecuting --> ActionFailed: Action fails
    ActionCompleted --> ActionExecuting: Next action
    ActionCompleted --> AssertionValidation: All actions done
    AssertionValidation --> TestPassed: Assertions pass
    AssertionValidation --> TestFailed: Assertions fail
    ActionFailed --> TestFailed: Propagate failure
    TestPassed --> Cleanup: Clean test data
    TestFailed --> Cleanup: Clean test data
    Cleanup --> [*]: Test complete
```

## Security Architecture

### IAM Permissions Model

```mermaid
graph TB
    subgraph "CLI Execution Role"
        CLI_PERMS[CLI Permissions]
        SFN_EXEC[Step Functions Execute]
        SFN_READ[Step Functions Describe]
        LOGS_READ[CloudWatch Logs Read]
    end
    
    subgraph "Step Functions Role"
        SFN_PERMS[SFN Permissions]
        LAMBDA_INVOKE[Lambda Invoke]
        LAMBDA_READ[Lambda Read]
    end
    
    subgraph "Lambda Execution Roles"
        LAMBDA_PERMS[Lambda Permissions]
        DDB_ACCESS[DynamoDB Access]
        HTTP_ACCESS[HTTP Outbound]
        LOGS_WRITE[CloudWatch Logs Write]
    end
    
    CLI_PERMS --> SFN_EXEC
    CLI_PERMS --> SFN_READ
    CLI_PERMS --> LOGS_READ
    
    SFN_PERMS --> LAMBDA_INVOKE
    SFN_PERMS --> LAMBDA_READ
    
    LAMBDA_PERMS --> DDB_ACCESS
    LAMBDA_PERMS --> HTTP_ACCESS
    LAMBDA_PERMS --> LOGS_WRITE
```

## Scalability Considerations

### Concurrent Test Execution

```mermaid
graph LR
    subgraph "Test Orchestrator"
        CLI[CLI Tool]
    end
    
    subgraph "Parallel Executions"
        SFN1[Step Function 1]
        SFN2[Step Function 2]
        SFN3[Step Function N]
    end
    
    subgraph "Shared Resources"
        LAMBDA_POOL[Lambda Function Pool]
        TARGET_SERVICES[Target Services]
    end
    
    CLI --> SFN1
    CLI --> SFN2
    CLI --> SFN3
    
    SFN1 --> LAMBDA_POOL
    SFN2 --> LAMBDA_POOL
    SFN3 --> LAMBDA_POOL
    
    LAMBDA_POOL --> TARGET_SERVICES
```

### Resource Limits and Considerations

| Component | Limit | Consideration |
|-----------|--------|---------------|
| Step Functions | 25,000 state transitions | Monitor execution complexity |
| Lambda Concurrent Executions | 1,000 (default) | Request limit increases for high concurrency |
| API Gateway | 10,000 RPS | Consider throttling for load tests |
| DynamoDB | 40,000 RCU/WCU | Scale based on test data requirements |

## Error Handling Architecture

### Error Propagation Flow

```mermaid
graph TD
    ACTION[Atomic Action] --> SUCCESS{Success?}
    SUCCESS -->|Yes| NEXT[Next Action]
    SUCCESS -->|No| RETRY{Retry?}
    
    RETRY -->|Yes| BACKOFF[Exponential Backoff]
    BACKOFF --> ACTION
    RETRY -->|No| FAIL[Action Failed]
    
    FAIL --> LOG[Log Error Details]
    LOG --> CLEANUP[Cleanup Resources]
    CLEANUP --> REPORT[Report Test Failure]
    
    NEXT --> COMPLETE{All Done?}
    COMPLETE -->|No| ACTION
    COMPLETE -->|Yes| VALIDATE[Validate Assertions]
    VALIDATE --> FINAL[Test Complete]
```

## Monitoring and Observability

### Logging Architecture

```mermaid
graph TB
    subgraph "Application Logs"
        CLI_LOGS[CLI Debug Logs]
        LAMBDA_LOGS[Lambda Function Logs]
        SFN_LOGS[Step Functions Logs]
    end
    
    subgraph "AWS CloudWatch"
        LOG_GROUPS[CloudWatch Log Groups]
        METRICS[CloudWatch Metrics]
        ALARMS[CloudWatch Alarms]
    end
    
    subgraph "Monitoring Dashboard"
        DASHBOARD[CloudWatch Dashboard]
        INSIGHTS[CloudWatch Insights]
    end
    
    CLI_LOGS --> LOG_GROUPS
    LAMBDA_LOGS --> LOG_GROUPS
    SFN_LOGS --> LOG_GROUPS
    
    LOG_GROUPS --> METRICS
    METRICS --> ALARMS
    
    LOG_GROUPS --> DASHBOARD
    METRICS --> DASHBOARD
    LOG_GROUPS --> INSIGHTS
```

## Performance Architecture

### Test Execution Optimization

```mermaid
graph LR
    subgraph "Performance Optimizations"
        PARALLEL[Parallel Actions]
        CACHE[Response Caching]
        POOL[Connection Pooling]
        BATCH[Batch Operations]
    end
    
    subgraph "Monitoring"
        LATENCY[Latency Metrics]
        THROUGHPUT[Throughput Metrics]
        ERRORS[Error Rates]
    end
    
    PARALLEL --> LATENCY
    CACHE --> LATENCY
    POOL --> THROUGHPUT
    BATCH --> THROUGHPUT
    
    LATENCY --> ERRORS
    THROUGHPUT --> ERRORS
```

## Deployment Architecture

### CI/CD Pipeline Integration

```mermaid
graph LR
    DEV[Development] --> BUILD[Build & Test]
    BUILD --> STAGE[Staging Deploy]
    STAGE --> E2E[E2E Tests]
    E2E --> PROD[Production Deploy]
    
    subgraph "Test Framework"
        E2E --> CLI[CLI Tool]
        CLI --> SCENARIOS[Test Scenarios]
        SCENARIOS --> RESULTS[Test Results]
    end
    
    RESULTS --> APPROVE{Manual Approval?}
    APPROVE -->|Pass| PROD
    APPROVE -->|Fail| DEV
```

This architecture documentation provides a comprehensive view of how the AWS Integration Tests CLI is structured and how its components interact to provide a robust testing framework for AWS microservices.
