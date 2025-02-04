import json

import urllib3
import psycopg2
from tenacity import *
from opensearchpy import OpenSearch
from opensearchpy import helpers as opensearch_helpers
from opensearchpy.exceptions import OpenSearchException

from ..util.airflow import get_postgres_conn
from ..util.log import logger

github_headers = {'Connection': 'keep-alive', 'Accept-Encoding': 'gzip, deflate, br', 'Accept': '*/*',
                  'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36', }


class HttpGetException(Exception):
    def __init__(self, message, status):
        super().__init__(message, status)
        self.message = message
        self.status = status


# retry 防止SSL解密错误，请正确处理是否忽略证书有效性
@retry(stop=stop_after_attempt(3),
       wait=wait_fixed(1),
       retry=retry_if_exception_type(urllib3.exceptions.HTTPError))
def do_get_result(req_session, url, headers, params):
    # 尝试处理网络请求错误
    # session.mount('http://', HTTPAdapter(
    #     max_retries=Retry(total=5, method_whitelist=frozenset(['GET', 'POST']))))  # 设置 post()方法进行重访问
    # session.mount('https://', HTTPAdapter(
    #     max_retries=Retry(total=5, method_whitelist=frozenset(['GET', 'POST']))))  # 设置 post()方法进行重访问
    # raise urllib3.exceptions.SSLError('获取github commits 失败！')

    res = req_session.get(url, headers=headers, params=params)
    if res.status_code >= 300:
        logger.warning(f"url:{url}")
        logger.warning(f"headers:{headers}")
        logger.warning(f"params:{params}")
        logger.warning(f"text:{res.text}")
        raise HttpGetException('http get 失败！')
    return res


def get_opensearch_client(opensearch_conn_infos):
    client = OpenSearch(
        hosts=[{'host': opensearch_conn_infos["HOST"], 'port': opensearch_conn_infos["PORT"]}],
        http_compress=True,
        http_auth=(opensearch_conn_infos["USER"], opensearch_conn_infos["PASSWD"]),
        use_ssl=True,
        verify_certs=False,
        ssl_assert_hostname=False,
        ssl_show_warn=False
    )
    return client


# retry_state <class 'tuple'> attr
# {
# 'start_time': 36837.02790198,
# 'retry_object': <Retrying object at 0x7f8e53089760 (
# stop=<tenacity.stop.stop_after_attempt object at 0x7f8e53089730>,
# wait=<tenacity.wait.wait_fixed object at 0x7f8e53089520>,
# sleep=<function sleep at 0x7f8e6d7db0d0>,
# retry=<tenacity.retry.retry_if_exception_type object at 0x7f8e53089550>,
# before=<function before_nothing at 0x7f8e6d7dbb80>,
# after=<function after_nothing at 0x7f8e6d7e4d30>)>,
# 'fn': <function do_opensearch_bulk at 0x7f8e53079310>,
# 'args': (<OpenSearch([{'host': '192.168.8.201', 'port': '9200'}])>, []),
# 'kwargs': {},
# 'attempt_number': 3,
# 'outcome': <Future at 0x7f8e52f082b0 state=finished raised HTTPError>,
# 'outcome_timestamp': 36839.030161701, 'idle_for': 2.0, 'next_action': None
# }
def do_opensearch_bulk_error_callback(retry_state):
    postgres_conn = get_postgres_conn()
    sql = '''INSERT INTO retry_data(
                owner, repo, type, data) 
                VALUES (%s, %s, %s, %s);'''
    try:
        cur = postgres_conn.cursor()
        owner = retry_state.args[2]
        repo = retry_state.args[3]
        for bulk_item in retry_state.args[1]:
            cur.execute(sql, (owner, repo, 'opensearch_bulk', json.dumps(bulk_item)))
        postgres_conn.commit()
        cur.close()
    except (psycopg2.DatabaseError) as error:
        logger.error(f"psycopg2.DatabaseError:{error}")

    finally:
        if postgres_conn is not None:
            postgres_conn.close()

    return retry_state.outcome.result()


# retry 防止OpenSearchException
@retry(stop=stop_after_attempt(3),
       wait=wait_fixed(1),
       retry_error_callback=do_opensearch_bulk_error_callback,
       retry=(retry_if_exception_type(OSError) | retry_if_exception_type(urllib3.exceptions.HTTPError) | retry_if_exception_type(OpenSearchException))
       )
def do_opensearch_bulk(opensearch_client, bulk_all_data, owner, repo):
    logger.info(f"owner:{owner},repo:{repo}::do_opensearch_bulk")

    success, failed = opensearch_helpers.bulk(client=opensearch_client, actions=bulk_all_data)
    # 强制抛出异常
    # raise OpenSearchException("do_opensearch_bulk Error")
    return success, failed
