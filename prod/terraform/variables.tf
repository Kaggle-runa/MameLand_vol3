variable "project_id" {
  type = string
}
variable "region" {
  type = string
}
variable "sa_iam_config" {
  type = list(object({
    sa_name   = string
    iam_roles = list(string)
  }))
}
variable "netkeiba_login_id" {
  type = string
}
variable "netkeiba_login_password" {
  type = string
}
variable "notification_email" {
  type        = string
  description = "アラート通知を受け取るメールアドレス"
}
