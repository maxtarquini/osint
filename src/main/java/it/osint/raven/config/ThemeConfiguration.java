package it.osint.raven.config;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class ThemeConfiguration {
    private String onlineColor;
    private String offlineColor;
    private String invalidColor;

    public static ThemeConfiguration defaults() {
        return new ThemeConfiguration("GREEN_BRIGHT", "RED_BRIGHT", "YELLOW_BRIGHT");
    }
}
