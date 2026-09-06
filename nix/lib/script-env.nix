config:
{
  PROJECT_NAME = config.projectName;
  PROJECT_DIR_VAR = config.projectDirVar;
  ODOO_VERSION = config.odooVersion;
  ODOO_MAJOR = config.derived.odooMajor;
  PYTHON_VERSION = config.python;
  SERVICE_SUFFIX = config.serviceSuffix;
  NIX_PROFILE_REL = config.derived.nixProfileRel;
  NIX_PROFILE_FLAG = config.derived.nixProfileFlag;
  ODOO_CMD = config.derived.odooCmd;
  ODOO_HTTP_PORT = config.ports.http;
  ODOO_GEVENT_PORT = config.ports.gevent;
  NGINX_PORT = config.ports.nginx;
  POSTGRES_PORT = config.ports.pg;
  DB_NAME = config.dbName;
  DB_USER = config.dbUser;
  DB_PASSWORD_FILE = if config.dbPasswordFile == null then "" else config.dbPasswordFile;
  TICKETS_MCP = config.ticketsMcp;
  ODOO_PROD_URL = config.odooProdUrl;
  USE_QUEUE_JOB = config.useQueueJob;
  BACKUP_S3_BUCKET = config.backupS3Bucket;
  ENABLE_BACKUP = config.derived.withBackup;
  ENABLE_SSH = config.derived.withSsh;
  ENABLE_VSCODE = config.editor == "vscode";
  PROD_SSH_HOST = config.prodSshHost;
  PROD_SSH_USER = config.prodSshUser;
  PROD_WEB_URL = config.prodWebUrl;
  TEST_SSH_HOST = config.testSshHost;
  TEST_SSH_USER = config.testSshUser;
  TEST_SSH_PORT = config.testSshPort;
  TEST_LOCAL_FORWARD = config.testLocalForward;
  TEST_WEB_URL = config.testWebUrl;
}
