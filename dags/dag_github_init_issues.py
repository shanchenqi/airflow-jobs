from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator

# v0.0.1

with DAG(
        dag_id='github_init_issues_v1',
        schedule_interval=None,
        start_date=datetime(2000, 1, 1),
        catchup=False,
        tags=['github'],
) as dag:
    def scheduler_init_sync_github_issues(ds, **kwargs):
        return 'End:scheduler_init_sync_github_issues'


    op_scheduler_init_sync_github_issues = PythonOperator(
        task_id='scheduler_init_sync_github_issues',
        python_callable=scheduler_init_sync_github_issues
    )


    def do_init_sync_github_issues(params):
        from airflow.models import Variable
        from libs.github import init_issues

        github_tokens = Variable.get("github_tokens", deserialize_json=True)
        opensearch_conn_infos = Variable.get("opensearch_conn_data", deserialize_json=True)

        owner = params["owner"]
        repo = params["repo"]
        # since = params["since"]
        since = None

        do_init_sync_info = init_issues.init_sync_github_issues(
            github_tokens, opensearch_conn_infos, owner, repo, since)

        return "End:do_init_sync_github_commit"


    need_do_init_sync_ops = []

    from airflow.models import Variable

    need_init_sync_github_issues_repos = Variable.get("need_init_sync_github_issues_list", deserialize_json=True)

    for init_sync_github_issues_repo in need_init_sync_github_issues_repos:
        op_do_init_sync_github_issues = PythonOperator(
            task_id='do_init_sync_github_commit_{owner}_{repo}'.format(
                owner=init_sync_github_issues_repo["owner"],
                repo=init_sync_github_issues_repo["repo"]),
            python_callable=do_init_sync_github_issues,
            op_kwargs={'params': init_sync_github_issues_repo},
        )
        op_scheduler_init_sync_github_issues >> op_do_init_sync_github_issues
