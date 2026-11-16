-- 降级模型族与冻结批次：与 ORM 定义一致，供已有库手工升级
CREATE TABLE IF NOT EXISTS `families` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) DEFAULT NULL,
  `features` json DEFAULT NULL,
  `alphas` json DEFAULT NULL,
  `state` varchar(20) DEFAULT NULL,
  `result` json DEFAULT NULL,
  `error` text,
  `created` varchar(40) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `batches` (
  `id` int NOT NULL AUTO_INCREMENT,
  `family_id` int NOT NULL,
  `batch_key` varchar(64) NOT NULL,
  `state` varchar(20) DEFAULT NULL,
  `rows` json DEFAULT NULL,
  `result` json DEFAULT NULL,
  `error` text,
  `created` varchar(40) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_batch_family_key` (`family_id`,`batch_key`),
  KEY `family_id` (`family_id`),
  CONSTRAINT `batches_ibfk_1` FOREIGN KEY (`family_id`) REFERENCES `families` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
