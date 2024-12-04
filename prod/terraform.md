# 定常作業
```sh
# 初期化
terraform init

# 実行内容確認
terraform plan -var-file="terraform.tfvars"

# 実行
terraform apply -var-file="terraform.tfvars"
```

# 一部だけapply
terraform apply --target=google_storage_bucket.gcf_source

# 手動でリソースを消した場合
```sh
# 対象リソースを確認
terraform state list

# tfstateファイルから削除
terraform state rm <resource_type>.<resource_name>
```
