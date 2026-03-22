import { FormEvent, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, Download, LoaderCircle } from 'lucide-react';

import { Button } from './ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Input } from './ui/input';
import { Label } from './ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select';

const countryData: Record<string, string[]> = {
  'United States': ['New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix', 'Philadelphia', 'San Antonio', 'San Diego', 'Dallas', 'San Jose'],
  'United Kingdom': ['London', 'Birmingham', 'Manchester', 'Liverpool', 'Leeds', 'Sheffield', 'Bristol', 'Glasgow', 'Edinburgh', 'Cardiff'],
  Canada: ['Toronto', 'Montreal', 'Vancouver', 'Calgary', 'Edmonton', 'Ottawa', 'Winnipeg', 'Quebec City', 'Hamilton', 'Kitchener'],
  Australia: ['Sydney', 'Melbourne', 'Brisbane', 'Perth', 'Adelaide', 'Gold Coast', 'Canberra', 'Newcastle', 'Wollongong', 'Hobart'],
  Germany: ['Berlin', 'Hamburg', 'Munich', 'Cologne', 'Frankfurt', 'Stuttgart', 'Dusseldorf', 'Dortmund', 'Essen', 'Leipzig'],
  France: ['Paris', 'Marseille', 'Lyon', 'Toulouse', 'Nice', 'Nantes', 'Strasbourg', 'Montpellier', 'Bordeaux', 'Lille'],
  India: ['Mumbai', 'Delhi', 'Bangalore', 'Hyderabad', 'Chennai', 'Kolkata', 'Pune', 'Ahmedabad', 'Jaipur', 'Surat'],
  Japan: ['Tokyo', 'Yokohama', 'Osaka', 'Nagoya', 'Sapporo', 'Fukuoka', 'Kobe', 'Kyoto', 'Kawasaki', 'Saitama'],
  China: ['Shanghai', 'Beijing', 'Guangzhou', 'Shenzhen', 'Chengdu', 'Hangzhou', 'Wuhan', 'Xian', 'Chongqing', 'Tianjin'],
  Brazil: ['Sao Paulo', 'Rio de Janeiro', 'Brasilia', 'Salvador', 'Fortaleza', 'Belo Horizonte', 'Manaus', 'Curitiba', 'Recife', 'Porto Alegre'],
};

type BusinessPreview = {
  name?: string;
  phone?: string;
  website?: string;
};

export function BusinessInfoForm() {
  const [businessType, setBusinessType] = useState('');
  const [country, setCountry] = useState('');
  const [city, setCity] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [quotaLeft, setQuotaLeft] = useState<number | null>(null);
  const [isCheckingQuota, setIsCheckingQuota] = useState(false);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [downloadUrl, setDownloadUrl] = useState('');
  const [businessCount, setBusinessCount] = useState<number | null>(null);
  const [businesses, setBusinesses] = useState<BusinessPreview[]>([]);

  const countries = Object.keys(countryData);
  const cities = country ? countryData[country] : [];

  const handleCountryChange = (value: string) => {
    setCountry(value);
    setCity('');
  };

  const checkQuota = async () => {
    if (!apiKey.trim()) return;
    setIsCheckingQuota(true);
    try {
      const res = await fetch('http://localhost:5000/api/check-quota', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey }),
      });
      const data = await res.json();
      if (res.ok) {
        setQuotaLeft(data.total_searches_left ?? 0);
      } else {
        setQuotaLeft(null);
        setError(data?.error || 'Failed to check quota.');
      }
    } catch {
      setQuotaLeft(null);
    } finally {
      setIsCheckingQuota(false);
    }
  };

  const isFormValid = businessType && country && city && apiKey;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    setError('');
    setSuccessMessage('');
    setDownloadUrl('');
    setBusinessCount(null);
    setBusinesses([]);
    setIsSubmitting(true);

    try {
      const response = await fetch('http://localhost:5000/api/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type_of_business: businessType,
          city,
          country,
          api_key: apiKey,
        }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.error || 'Request failed. Please try again.');
      }

      const fileUrl = payload?.file_url ? `http://localhost:5000${payload.file_url}` : '';
      setSuccessMessage(payload?.message || 'Extraction completed successfully.');
      setDownloadUrl(fileUrl);
      setBusinessCount(typeof payload?.business_count === 'number' ? payload.business_count : 0);
      setBusinesses(Array.isArray(payload?.businesses) ? payload.businesses : []);
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : 'Unknown error.';
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-gradient-to-br from-blue-50 to-indigo-100">
      <Card className="w-full max-w-3xl shadow-lg">
        <CardHeader>
          <CardTitle>Business Information Extractor</CardTitle>
          <CardDescription>
            Submit your search details, run extraction on the backend, and download the generated Excel report.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="businessType">Business Type</Label>
              <Input
                id="businessType"
                type="text"
                placeholder="e.g., Restaurant, Retail, Technology"
                value={businessType}
                onChange={(e) => setBusinessType(e.target.value)}
                required
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="country">Country</Label>
              <Select value={country} onValueChange={handleCountryChange} required>
                <SelectTrigger id="country" className="w-full">
                  <SelectValue placeholder="Select a country" />
                </SelectTrigger>
                <SelectContent>
                  {countries.map((countryName) => (
                    <SelectItem key={countryName} value={countryName}>
                      {countryName}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="city">City</Label>
              <Select value={city} onValueChange={setCity} disabled={!country} required>
                <SelectTrigger id="city" className="w-full">
                  <SelectValue placeholder={country ? 'Select a city' : 'Select a country first'} />
                </SelectTrigger>
                <SelectContent>
                  {cities.map((cityName) => (
                    <SelectItem key={cityName} value={cityName}>
                      {cityName}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="apiKey">API Key</Label>
              <div className="flex gap-2">
                <Input
                  id="apiKey"
                  type="password"
                  placeholder="Enter your SerpAPI key"
                  value={apiKey}
                  onChange={(e) => { setApiKey(e.target.value); setQuotaLeft(null); }}
                  required
                  className="flex-1"
                />
                <Button
                  type="button"
                  variant="outline"
                  disabled={!apiKey.trim() || isCheckingQuota}
                  onClick={checkQuota}
                >
                  {isCheckingQuota ? (
                    <LoaderCircle className="h-4 w-4 animate-spin" />
                  ) : (
                    'Check Quota'
                  )}
                </Button>
              </div>
              {quotaLeft !== null && (
                <div className={`flex items-center gap-2 text-sm font-medium ${
                  quotaLeft > 0
                    ? 'text-emerald-700'
                    : 'text-red-600'
                }`}>
                  {quotaLeft > 0 ? (
                    <><CheckCircle2 className="h-4 w-4" /> {quotaLeft} searches remaining</>
                  ) : (
                    <><AlertCircle className="h-4 w-4" /> Quota exhausted — please use a different key</>
                  )}
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" className="flex-1 min-w-56" disabled={!isFormValid || isSubmitting}>
                {isSubmitting ? (
                  <>
                    <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
                    Running extraction...
                  </>
                ) : (
                  <>
                    <Download className="mr-2 h-4 w-4" />
                    Extract and Generate Excel
                  </>
                )}
              </Button>

              {downloadUrl && (
                <a
                  href={downloadUrl}
                  className="inline-flex h-10 items-center justify-center rounded-md border border-input px-4 py-2 text-sm font-medium"
                >
                  <Download className="mr-2 h-4 w-4" />
                  Download Excel
                </a>
              )}
            </div>

            {successMessage && (
              <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-emerald-800">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <CheckCircle2 className="h-4 w-4" />
                  {successMessage}
                </div>
                {businessCount !== null && <p className="mt-1 text-sm">Businesses found: {businessCount}</p>}
              </div>
            )}

            {error && (
              <div className="rounded-md border border-red-300 bg-red-50 p-3 text-red-700">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <AlertCircle className="h-4 w-4" />
                  {error}
                </div>
              </div>
            )}

            {businesses.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-sm font-semibold">Preview (first 5 results)</h3>
                <div className="max-h-64 overflow-auto rounded-md border">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-muted/50">
                      <tr>
                        <th className="px-3 py-2">Name</th>
                        <th className="px-3 py-2">Phone</th>
                        <th className="px-3 py-2">Website</th>
                      </tr>
                    </thead>
                    <tbody>
                      {businesses.slice(0, 5).map((item, index) => (
                        <tr key={`${item.name || 'business'}-${index}`} className="border-t">
                          <td className="px-3 py-2">{item.name || '-'}</td>
                          <td className="px-3 py-2">{item.phone || '-'}</td>
                          <td className="px-3 py-2">
                            {item.website ? (
                              <a href={item.website} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">
                                {item.website}
                              </a>
                            ) : (
                              '-'
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
