import logging
import math

import boto3

MAX_N_DESCRIBE_SERVICES = 10


class AWSWrapper:
    def __init__(self, client):
        self._client = client

    def register_task_definition(self, task_definition, family):
        response = self._client.register_task_definition(family=family,
                                                         **task_definition)

        return response['taskDefinition']['revision']

    def run_release_task(self, cluster, service, task_definition):
        service_description = self._client.describe_services(cluster=cluster, services=[service])

        network_configuration = service_description['services'][0]['networkConfiguration']

        response = self._client.run_task(cluster=cluster,
                                         taskDefinition=task_definition,
                                         launchType='FARGATE',
                                         networkConfiguration=network_configuration)

        return response['tasks'][0]['taskArn']

    def has_task_finished(self, cluster, task_arn, wait_seconds=5):
        task_description = self._client.describe_tasks(cluster=cluster, tasks=[task_arn])

        if task_description['tasks'][0]['lastStatus'] == 'STOPPED':
            exit_code = task_description['tasks'][0]['containers'][0]['exitCode']
            if exit_code == 0:
                return True
            else:
                raise Exception('Exit code not 0, got: {}'.format(exit_code))

        return False

    def update_services(self, cluster, environment, project_name, revisions):
        for service_name, revision_number in revisions.items():
            service = "{}-{}".format(project_name, service_name)
            task_definition = "{}-{}-{}:{}".format(environment,
                                                   project_name,
                                                   service_name,
                                                   revision_number)

            logging.info("Updating service {} with td: {}".format(service, task_definition))
            self._client.update_service(cluster=cluster,
                                        service=service,
                                        taskDefinition=task_definition)

    def describe_services(self, cluster, services):
        n_requests = math.ceil(len(services) / MAX_N_DESCRIBE_SERVICES)
        service_descriptions = dict()

        for i in range(0, n_requests):
            services_batch = services[i * MAX_N_DESCRIBE_SERVICES:(i + 1) * MAX_N_DESCRIBE_SERVICES]
            aws_response = self._client.describe_services(cluster=cluster,
                                                          services=services_batch)
            response_batch = {
                service['serviceName']: {
                    deployment['status']: deployment['taskDefinition']
                    for deployment in service['deployments']
                }
                for service in aws_response['services']
            }

            service_descriptions.update(response_batch)

        return service_descriptions

    @classmethod
    def build(cls, account_id, role_name):
        client_sts = boto3.client('sts')  # AWS settings came from env vars

        role_arn = "arn:aws:iam::{}:role/sso/{}".format(account_id, role_name)
        assumed_role_object = client_sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName="AssumeRoleSession"
        )

        credentials = assumed_role_object['Credentials']

        client = boto3.client(
            'ecs',
            aws_access_key_id=credentials['AccessKeyId'],
            aws_secret_access_key=credentials['SecretAccessKey'],
            aws_session_token=credentials['SessionToken'],
        )

        return cls(client=client)
