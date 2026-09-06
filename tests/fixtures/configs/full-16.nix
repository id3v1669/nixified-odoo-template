{
  projectName = "ci-full";
  odooVersion = "16.0";
  useQueueJob = true;
  customRepoPattern = "git@github.com:acme/{}.git";
  customRepoName = "acme-addons";
  modulePrefix = "acme";
  ticketPrefix = "ACME";
  statusMcp = "teams";
  ticketsMcp = "odoo";
  odooProdUrl = "https://odoo.example.com";
  usePipeline = true;
  backupS3Bucket = "acme-backups";
  editor = "vscode";
  prodSshHost = "192.0.2.1";
  prodWebUrl = "https://odoo.example.com";
  testSshHost = "192.0.2.2";
}
