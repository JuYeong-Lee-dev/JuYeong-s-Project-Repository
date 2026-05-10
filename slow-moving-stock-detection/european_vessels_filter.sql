-- Filter slow-moving stock detection results to European shipping company vessels only.
-- Joins the detection table with vessel info to restrict by Group Owner Country.
-- Excludes internal/HQ vessels (HOTHR prefix).

CREATE TABLE slow_moving_european_vessels AS (
    SELECT
        a."U-CODE",
        a."적용 호선"        AS vessel_no,
        b."호선명"           AS vessel_name,
        b."Group Owner Country",
        b."Group Owner"
    FROM slow_moving_detection a
    LEFT JOIN vessel_info b
        ON a."적용 호선" = b."호선번호"
    WHERE a."적용 호선" NOT LIKE '%HOTHR%'
      AND b."Group Owner Country" IN (
        'AT - 오스트리아',  'BE - 벨기에',   'BG - 불가리아',
        'CH - 스위스',      'CY - 키프로스',  'DE - 독일',
        'DK - 덴마크',      'EE - 에스토니아','ES - 스페인',
        'FI - 핀란드',      'FO - 페로 제도', 'FR - 프랑스',
        'GB - 영국',        'GE - 조지아',    'GR - 그리스',
        'HR - 크로아티아',  'IM - 맨섬',      'IS - 아이슬란드',
        'IT - 이탈리아',    'JE - 저지섬',    'LT - 리투아니아',
        'LU - 룩셈부르크',  'LV - 라트비아',  'MC - 모나코',
        'MT - 몰타',        'NL - 네덜란드',  'NO - 노르웨이',
        'PL - 폴란드',      'PT - 포르투갈',  'SE - 스웨덴',
        'SI - 슬로베니아',  'UA - 우크라이나'
    )
);
